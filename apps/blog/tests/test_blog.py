"""Blog: admin CRUD + publish flow, public read API, and the AI writer."""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.blog import ai
from apps.blog.models import BlogPost, BlogStatus
from apps.storeconfig import services as config_services


def _admin_client():
    user = UserFactory(role=Role.ADMIN)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
def test_admin_create_post_derives_slug_and_reading_time() -> None:
    client, _ = _admin_client()
    body = " ".join(["word"] * 400)
    r = client.post(
        "/api/v1/admin/blog/posts/",
        {"title": "Best Hoodies in Lagos", "body": body},
        format="json",
    )
    assert r.status_code == 201
    post = BlogPost.objects.get()
    assert post.slug == "best-hoodies-in-lagos"
    assert post.status == BlogStatus.DRAFT
    assert post.reading_minutes == 2  # 400 words / 200 wpm
    assert post.excerpt  # auto-generated


@pytest.mark.django_db
def test_publish_makes_post_public() -> None:
    client, _ = _admin_client()
    created = client.post(
        "/api/v1/admin/blog/posts/",
        {"title": "Style guide", "body": "Hello world content."},
        format="json",
    ).data

    # Not visible until published.
    assert APIClient().get("/api/v1/blog/posts/").data["count"] == 0

    r = client.post(f"/api/v1/admin/blog/posts/{created['id']}/publish/")
    assert r.status_code == 200
    assert r.data["published_at"] is not None

    pub = APIClient().get("/api/v1/blog/posts/")
    assert pub.data["count"] == 1
    detail = APIClient().get("/api/v1/blog/posts/style-guide/")
    assert detail.status_code == 200
    assert detail.data["body"] == "Hello world content."


@pytest.mark.django_db
def test_ai_requires_api_key() -> None:
    client, _ = _admin_client()
    r = client.post("/api/v1/admin/blog/posts/ai/", {"topic": "Lagos fashion"}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_ai_generates_from_openrouter(monkeypatch) -> None:
    config_services.set_setting("blog.openrouter_api_key", "test-key")

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "How to Style a Hoodie",
                                    "excerpt": "A quick guide.",
                                    "meta_description": "Style your hoodie.",
                                    "tags": ["hoodie", "style"],
                                    "body": "## Intro\nWear it well.",
                                }
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: FakeResp())

    client, _ = _admin_client()
    r = client.post(
        "/api/v1/admin/blog/posts/ai/",
        {"topic": "hoodies", "keywords": "lagos hoodie"},
        format="json",
    )
    assert r.status_code == 200
    assert r.data["title"] == "How to Style a Hoodie"
    assert r.data["tags"] == ["hoodie", "style"]
    assert "Wear it well" in r.data["body"]
