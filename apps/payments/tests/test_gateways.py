"""Paystack + Flutterwave: signature verification, webhook → paid, idempotency.

Gateway HTTP calls (initialize / verify) are mocked, so these run with no real
account. The critical security paths — signature verification and server-side
re-verification before marking an order paid — are exercised end to end.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.test import override_settings

from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.orders import services as order_services
from apps.orders.models import OrderStatus
from apps.payments import providers
from apps.payments import services as payment_services
from apps.payments.models import Payment
from apps.payments.services import WebhookSignatureError
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


def _order(price="20.00", qty=1):
    """A real PENDING order + mock payment (intent_id is the gateway reference)."""
    cart = cart_services.get_or_create_cart(user=None, session_key="s1")
    v = make_variant(price, stock=10)
    cart_services.add_item(cart, variant_id=str(v.id), quantity=qty)
    cart_services.set_shipping(
        cart, {"name": "Buyer", "line1": "1 St", "city": "Town", "country": "US"}
    )
    order = order_services.checkout(cart, idempotency_key=f"k-{price}-{qty}", currency="USD")
    return order, order.payments.first()


class FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x"
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


# --------------------------------------------------------------------------- #
# Paystack
# --------------------------------------------------------------------------- #
@override_settings(PAYMENT_PROVIDER="paystack", PAYSTACK_SECRET_KEY="sk_test_x")
def test_paystack_create_intent_initializes_transaction(setup, monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResp(
            {
                "status": True,
                "data": {
                    "reference": json["reference"],
                    "authorization_url": "https://checkout.paystack.com/abc",
                },
            }
        )

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.get_payment_provider()
    intent = provider.create_intent(
        amount=Decimal("40.00"),
        currency="USD",
        reference="REF1",
        email="a@b.com",
        redirect_url="http://x",
        metadata={},
    )
    assert intent["authorization_url"] == "https://checkout.paystack.com/abc"
    assert intent["intent_id"] == "REF1"
    assert captured["json"]["amount"] == 4000  # 40.00 → subunit (kobo/cents)
    assert "transaction/initialize" in captured["url"]


def test_paystack_webhook_marks_order_paid_and_is_idempotent(setup, monkeypatch) -> None:
    order, payment = _order()
    ref = payment.intent_id
    cents = int(order.total_charged * 100)
    body = json.dumps(
        {
            "event": "charge.success",
            "data": {"id": 12345, "reference": ref, "status": "success",
                     "amount": cents, "currency": "USD"},
        }
    ).encode()
    sig = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()

    def fake_get(url, headers=None, timeout=None, params=None):
        assert reference in url  # Paystack verifies by reference
        return FakeResp(
            {"data": {"status": "success", "amount": cents, "currency": "USD", "reference": ref}}
        )

    reference = ref
    monkeypatch.setattr(providers.requests, "get", fake_get)
    with override_settings(PAYMENT_PROVIDER="paystack", PAYSTACK_SECRET_KEY="sk_test_x"):
        first = payment_services.process_webhook(provider_name="paystack", payload=body, signature=sig)
        second = payment_services.process_webhook(provider_name="paystack", payload=body, signature=sig)

    order.refresh_from_db()
    payment.refresh_from_db()
    assert first["status"] == "applied"
    assert second["status"] == "duplicate"
    assert payment.status == Payment.Status.SUCCEEDED
    assert order.paid_at is not None
    assert order.status != OrderStatus.PENDING


def test_paystack_bad_signature_rejected(setup) -> None:
    body = json.dumps({"event": "charge.success", "data": {"id": 1, "reference": "r"}}).encode()
    with override_settings(PAYMENT_PROVIDER="paystack", PAYSTACK_SECRET_KEY="sk_test_x"):
        with pytest.raises(WebhookSignatureError):
            payment_services.process_webhook(provider_name="paystack", payload=body, signature="bad")


def test_paystack_underpayment_not_applied(setup, monkeypatch) -> None:
    order, payment = _order(price="20.00")
    ref = payment.intent_id
    # The webhook *claims* the full amount, but the gateway's own verify endpoint
    # (source of truth) reports a smaller amount → must not mark paid.
    body = json.dumps(
        {"event": "charge.success",
         "data": {"id": 7, "reference": ref, "status": "success", "amount": 2000, "currency": "USD"}}
    ).encode()
    sig = hmac.new(b"sk_test_x", body, hashlib.sha512).hexdigest()

    def fake_get(url, headers=None, timeout=None, params=None):
        return FakeResp(
            {"data": {"status": "success", "amount": 500, "currency": "USD", "reference": ref}}
        )  # 5.00 < 20.00

    monkeypatch.setattr(providers.requests, "get", fake_get)
    with override_settings(PAYMENT_PROVIDER="paystack", PAYSTACK_SECRET_KEY="sk_test_x"):
        res = payment_services.process_webhook(provider_name="paystack", payload=body, signature=sig)

    order.refresh_from_db()
    assert res["status"] == "unverified"
    assert order.status == OrderStatus.PENDING
    assert order.paid_at is None


# --------------------------------------------------------------------------- #
# Flutterwave
# --------------------------------------------------------------------------- #
@override_settings(
    PAYMENT_PROVIDER="flutterwave",
    FLUTTERWAVE_SECRET_KEY="flw_test",
    FLUTTERWAVE_SECRET_HASH="hash123",
)
def test_flutterwave_create_intent_returns_link(setup, monkeypatch) -> None:
    def fake_post(url, json=None, headers=None, timeout=None):
        assert json["tx_ref"] == "REF2"
        return FakeResp({"status": "success", "data": {"link": "https://flutterwave.com/pay/xyz"}})

    monkeypatch.setattr(providers.requests, "post", fake_post)
    provider = providers.get_payment_provider()
    intent = provider.create_intent(
        amount=Decimal("92.00"),
        currency="USD",
        reference="REF2",
        email="a@b.com",
        redirect_url="http://x",
        metadata={},
    )
    assert intent["authorization_url"] == "https://flutterwave.com/pay/xyz"
    assert intent["intent_id"] == "REF2"


def test_flutterwave_webhook_marks_order_paid(setup, monkeypatch) -> None:
    order, payment = _order(price="50.00")
    ref = payment.intent_id
    amount = float(order.total_charged)
    body = json.dumps(
        {"event": "charge.completed",
         "data": {"id": 999, "tx_ref": ref, "status": "successful",
                  "amount": amount, "currency": "USD"}}
    ).encode()

    def fake_get(url, headers=None, timeout=None, params=None):
        assert "/transactions/999/verify" in url  # verified by gateway txn id
        return FakeResp(
            {"data": {"status": "successful", "amount": amount, "currency": "USD", "tx_ref": ref}}
        )

    monkeypatch.setattr(providers.requests, "get", fake_get)
    with override_settings(
        PAYMENT_PROVIDER="flutterwave",
        FLUTTERWAVE_SECRET_KEY="flw_test",
        FLUTTERWAVE_SECRET_HASH="hash123",
    ):
        res = payment_services.process_webhook(
            provider_name="flutterwave", payload=body, signature="hash123"
        )

    order.refresh_from_db()
    payment.refresh_from_db()
    assert res["status"] == "applied"
    assert payment.status == Payment.Status.SUCCEEDED
    assert order.paid_at is not None


def test_flutterwave_wrong_hash_rejected(setup) -> None:
    body = json.dumps({"event": "charge.completed", "data": {"id": 1, "tx_ref": "r"}}).encode()
    with override_settings(
        PAYMENT_PROVIDER="flutterwave",
        FLUTTERWAVE_SECRET_KEY="flw_test",
        FLUTTERWAVE_SECRET_HASH="hash123",
    ):
        with pytest.raises(WebhookSignatureError):
            payment_services.process_webhook(
                provider_name="flutterwave", payload=body, signature="WRONG"
            )
