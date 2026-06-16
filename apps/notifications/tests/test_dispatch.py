from __future__ import annotations

from unittest import mock

import pytest

from apps.notifications import events, services
from apps.notifications.channels.email import MemoryEmailBackend
from apps.notifications.channels.telegram import MemoryTelegramBackend
from apps.notifications.models import Channel, Notification, NotificationStatus


@pytest.fixture(autouse=True)
def _reset_outboxes():
    MemoryEmailBackend.outbox.clear()
    MemoryEmailBackend.fail_times = 0
    MemoryTelegramBackend.outbox.clear()
    MemoryTelegramBackend.fail_times = 0
    yield


@pytest.mark.django_db
def test_dispatch_email_renders_and_sends() -> None:
    services.dispatch(
        events.WELCOME,
        context={"name": "Sam"},
        dedupe_key="welcome:1",
        email_to="sam@example.com",
    )
    note = Notification.objects.get(channel=Channel.EMAIL, recipient="sam@example.com")
    assert note.status == NotificationStatus.SENT
    assert len(MemoryEmailBackend.outbox) == 1
    assert "Welcome" in MemoryEmailBackend.outbox[0].subject


@pytest.mark.django_db
def test_dispatch_is_idempotent() -> None:
    for _ in range(3):
        services.dispatch(
            events.WELCOME, context={"name": "A"}, dedupe_key="welcome:42", email_to="a@example.com"
        )
    # Only one notification + one delivery despite repeated dispatch.
    assert Notification.objects.filter(dedupe_key="welcome:42").count() == 1
    assert len(MemoryEmailBackend.outbox) == 1


@pytest.mark.django_db
def test_email_and_telegram_dispatched_together() -> None:
    services.dispatch(
        events.SHIPMENT_UPDATE,
        context={"order_number": "IC-1", "tracking_number": "TRK1", "carrier": "X"},
        dedupe_key="ship:1",
        email_to="buyer@example.com",
        telegram_chat_id="chat-1",
    )
    assert len(MemoryEmailBackend.outbox) == 1
    assert len(MemoryTelegramBackend.outbox) == 1
    assert "TRK1" in MemoryTelegramBackend.outbox[0][1]


@pytest.mark.django_db
def test_email_failure_does_not_block_telegram() -> None:
    # First email attempt fails; the task retries. Telegram is unaffected.
    MemoryEmailBackend.fail_times = 99  # always fail
    with mock.patch(
        "apps.notifications.tasks.deliver_notification.retry", side_effect=Exception("stop")
    ):
        services.dispatch(
            events.SHIPMENT_UPDATE,
            context={"order_number": "IC-2"},
            dedupe_key="ship:2",
            email_to="x@example.com",
            telegram_chat_id="chat-2",
        )
    email_note = Notification.objects.get(channel=Channel.EMAIL, recipient="x@example.com")
    tg_note = Notification.objects.get(channel=Channel.TELEGRAM, recipient="chat-2")
    assert email_note.status == NotificationStatus.FAILED
    assert tg_note.status == NotificationStatus.SENT  # telegram still delivered
    assert len(MemoryTelegramBackend.outbox) == 1


@pytest.mark.django_db
def test_retry_then_succeed() -> None:
    MemoryEmailBackend.fail_times = 1  # fail once, then succeed
    # Simulate the task retrying by invoking delivery twice (eager retry is raised).
    with mock.patch(
        "apps.notifications.tasks.deliver_notification.retry", side_effect=Exception("retry")
    ):
        try:
            services.dispatch(
                events.WELCOME,
                context={"name": "R"},
                dedupe_key="welcome:r",
                email_to="r@example.com",
            )
        except Exception:
            pass
    note = Notification.objects.get(dedupe_key="welcome:r")
    assert note.status == NotificationStatus.FAILED  # first attempt failed
    # Re-deliver (as a retry would) → now succeeds.
    from apps.notifications.tasks import deliver_notification

    deliver_notification(str(note.id))
    note.refresh_from_db()
    assert note.status == NotificationStatus.SENT
