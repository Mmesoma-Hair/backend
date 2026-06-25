from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.common.models import AuditLog
from apps.storeconfig import selectors, services
from apps.storeconfig.models import Setting


@pytest.mark.django_db
def test_get_setting_returns_spec_default_when_unset() -> None:
    assert selectors.get_setting("store.name") == "Eandewigs"
    assert selectors.get_setting("currency.base") == "USD"
    assert selectors.get_setting("currency.enabled") == ["USD", "EUR", "GBP"]


@pytest.mark.django_db
def test_unknown_key_raises() -> None:
    with pytest.raises(ValidationError):
        selectors.get_setting("does.not.exist")


@pytest.mark.django_db
def test_set_setting_overrides_default_and_persists() -> None:
    services.set_setting("store.name", "Acme")
    assert selectors.get_setting("store.name") == "Acme"
    assert Setting.objects.filter(key="store.name").exists()


@pytest.mark.django_db
def test_set_setting_coerces_types() -> None:
    services.set_setting("currency.refresh_minutes", "90")
    assert selectors.get_setting("currency.refresh_minutes") == 90

    services.set_setting("features.guest_payers", "false")
    assert selectors.get_setting("features.guest_payers") is False


@pytest.mark.django_db
def test_invalid_value_rejected() -> None:
    with pytest.raises(ValidationError):
        services.set_setting("currency.base", "DOLLARS")  # not 3 letters
    with pytest.raises(ValidationError):
        services.set_setting("currency.fx_markup_percent", "-5")  # negative


@pytest.mark.django_db
def test_set_setting_writes_audit_entry() -> None:
    services.set_setting("store.name", "Audited")
    entry = AuditLog.objects.get(target_type="storeconfig.Setting", target_id="store.name")
    assert entry.action == AuditLog.Action.CREATE
    assert entry.changes["store.name"]["after"] == "Audited"


@pytest.mark.django_db
def test_reset_setting_falls_back_to_default() -> None:
    services.set_setting("store.name", "Temp")
    services.reset_setting("store.name")
    assert selectors.get_setting("store.name") == "Eandewigs"
    assert not Setting.objects.filter(key="store.name").exists()


@pytest.mark.django_db
def test_social_links_default_and_valid_write() -> None:
    default = selectors.get_setting("footer.social_links")
    assert isinstance(default, list) and default
    assert {"name", "url", "icon"} <= set(default[0])

    services.set_setting(
        "footer.social_links",
        [{"name": "X", "url": "https://x.com/eandewigs", "icon": "x"}],
    )
    stored = selectors.get_setting("footer.social_links")
    assert stored == [{"name": "X", "url": "https://x.com/eandewigs", "icon": "x"}]


@pytest.mark.django_db
def test_social_links_rejects_malformed() -> None:
    with pytest.raises(ValidationError):
        services.set_setting("footer.social_links", "not-a-list")
    with pytest.raises(ValidationError):
        # missing 'icon'
        services.set_setting("footer.social_links", [{"name": "X", "url": "https://x.com"}])
    with pytest.raises(ValidationError):
        # blank name
        services.set_setting(
            "footer.social_links", [{"name": "  ", "url": "https://x.com", "icon": "x"}]
        )


@pytest.mark.django_db
def test_social_links_is_public() -> None:
    from apps.storeconfig.schema import PUBLIC_KEYS

    assert "footer.social_links" in PUBLIC_KEYS


@pytest.mark.django_db
def test_set_many_is_atomic() -> None:
    with pytest.raises(ValidationError):
        services.set_many({"store.name": "Ok", "currency.base": "XX"})
    # The valid key must not have been written because validation failed first.
    assert not Setting.objects.filter(key="store.name").exists()
