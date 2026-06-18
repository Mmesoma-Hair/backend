"""Provider-agnostic payment integration.

``PaymentProvider`` is the seam every gateway implements. Three concrete
providers ship:

* ``MockProvider`` — no external account; mints deterministic ids and HMAC-signs
  webhook payloads so signature + idempotency handling can be exercised locally.
* ``PaystackProvider`` — initializes a transaction and verifies ``charge.success``
  webhooks (HMAC-SHA512 of the raw body with the secret key).
* ``FlutterwaveProvider`` — creates a payment link and verifies ``charge.completed``
  webhooks (the ``verif-hash`` header must equal the configured secret hash).

For real providers, ``create_intent`` returns an ``authorization_url`` the
shopper is redirected to. Webhooks are re-verified server-side via the gateway's
API (``verify_transaction``) before an order is marked paid — never trust the
webhook body alone.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings

from . import config


class PaymentError(Exception):
    pass


class PaymentProvider(ABC):
    name = "base"
    # HTTP header the gateway puts its webhook signature in.
    signature_header = "X-Signature"

    @abstractmethod
    def create_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
        email: str,
        redirect_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Start a transaction. Return at least {'intent_id', 'status'} and, for
        hosted gateways, 'authorization_url' to redirect the shopper to."""

    @abstractmethod
    def verify_signature(self, *, payload: bytes, signature: str) -> bool:
        """Verify a webhook signature."""

    @abstractmethod
    def parse_event(self, payload: bytes) -> dict[str, Any]:
        """Parse a webhook body into {'event_id', 'type', 'intent_id', 'status'}.

        ``status`` is normalized to 'succeeded' / 'failed' / other.
        """

    def verify_transaction(self, *, reference: str, txn_id: str) -> dict[str, Any] | None:
        """Re-confirm a transaction with the gateway API before applying it.

        ``reference`` is our own tx ref; ``txn_id`` is the gateway's transaction
        id from the webhook. Returns {'status', 'amount', 'currency', 'reference'}
        or None if unsupported (mock).
        """
        return None

    def verify_credentials(self) -> dict[str, Any]:
        """Check the configured keys work by making a cheap authenticated call.

        Returns {'ok': bool, 'message': str}.
        """
        return {"ok": True, "message": "OK"}


class MockProvider(PaymentProvider):
    name = "mock"
    signature_header = "X-Signature"

    @property
    def _secret(self) -> bytes:
        return settings.PAYMENT_WEBHOOK_SECRET.encode()

    def create_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
        email: str,
        redirect_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "intent_id": reference,
            "status": "requires_confirmation",
            "authorization_url": "",
            "client_secret": f"mock_secret_{secrets.token_hex(8)}",
        }

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify_signature(self, *, payload: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(payload), signature or "")

    def parse_event(self, payload: bytes) -> dict[str, Any]:
        data = json.loads(payload.decode() or "{}")
        return {
            "event_id": data.get("id", ""),
            "type": data.get("type", ""),
            "intent_id": data.get("intent_id", ""),
            "status": data.get("status", ""),
        }

    def verify_credentials(self) -> dict[str, Any]:
        return {"ok": True, "message": "Mock provider active — no external account needed."}

    def build_event(self, *, intent_id: str, status: str = "succeeded") -> tuple[bytes, str]:
        """Build a signed webhook body (used by the mock confirm endpoint/tests)."""
        body = json.dumps(
            {
                "id": f"mock_evt_{secrets.token_hex(8)}",
                "type": f"payment.{status}",
                "intent_id": intent_id,
                "status": status,
            }
        ).encode()
        return body, self.sign(body)


class PaystackProvider(PaymentProvider):
    """Paystack: https://paystack.com/docs/api/"""

    name = "paystack"
    signature_header = "x-paystack-signature"
    BASE = "https://api.paystack.co"

    @property
    def _secret(self) -> str:
        return config.paystack_secret_key()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}", "Content-Type": "application/json"}

    def verify_credentials(self) -> dict[str, Any]:
        if not self._secret:
            return {"ok": False, "message": "Paystack secret key is not set."}
        try:
            resp = requests.get(
                f"{self.BASE}/balance",
                headers=self._headers(),
                timeout=settings.PAYMENT_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            return {"ok": False, "message": f"Could not reach Paystack: {exc}"}
        if resp.status_code == 401:
            return {"ok": False, "message": "Paystack rejected the secret key (401)."}
        if resp.status_code >= 400:
            return {"ok": False, "message": f"Paystack returned {resp.status_code}."}
        return {"ok": True, "message": "Paystack secret key is valid."}

    def create_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
        email: str,
        redirect_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._secret:
            raise PaymentError("Paystack secret key is not configured.")
        # Paystack amounts are in the currency subunit (kobo, cents, pesewas).
        subunit = int((amount * 100).to_integral_value())
        payload = {
            "email": email or "customer@example.com",
            "amount": subunit,
            "currency": currency.upper(),
            "reference": reference,
            "callback_url": redirect_url,
            "metadata": metadata,
        }
        try:
            resp = requests.post(
                f"{self.BASE}/transaction/initialize",
                json=payload,
                headers=self._headers(),
                timeout=settings.PAYMENT_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise PaymentError(f"Paystack request failed: {exc}") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not body.get("status"):
            raise PaymentError(f"Paystack init failed: {body.get('message', resp.text[:200])}")
        data = body["data"]
        return {
            "intent_id": data.get("reference", reference),
            "status": "pending",
            "authorization_url": data["authorization_url"],
        }

    def verify_signature(self, *, payload: bytes, signature: str) -> bool:
        if not self._secret:
            return False
        expected = hmac.new(self._secret.encode(), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def parse_event(self, payload: bytes) -> dict[str, Any]:
        body = json.loads(payload.decode() or "{}")
        data = body.get("data", {}) or {}
        event_type = body.get("event", "")
        succeeded = event_type == "charge.success" and data.get("status") == "success"
        return {
            "event_id": str(data.get("id", "")),
            "type": event_type,
            "intent_id": data.get("reference", ""),
            "status": "succeeded" if succeeded else data.get("status", ""),
        }

    def verify_transaction(self, *, reference: str, txn_id: str) -> dict[str, Any] | None:
        # Paystack's canonical verify is by reference.
        try:
            resp = requests.get(
                f"{self.BASE}/transaction/verify/{reference}",
                headers=self._headers(),
                timeout=settings.PAYMENT_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise PaymentError(f"Paystack verify failed: {exc}") from exc
        body = resp.json() if resp.content else {}
        data = body.get("data", {}) or {}
        amount = data.get("amount")
        return {
            "status": "succeeded" if data.get("status") == "success" else data.get("status", ""),
            "amount": (Decimal(amount) / 100) if amount else Decimal("0"),
            "currency": (data.get("currency") or "").upper(),
            "reference": data.get("reference", ""),
        }


class FlutterwaveProvider(PaymentProvider):
    """Flutterwave: https://developer.flutterwave.com/docs"""

    name = "flutterwave"
    signature_header = "verif-hash"
    BASE = "https://api.flutterwave.com/v3"

    @property
    def _secret(self) -> str:
        return config.flutterwave_secret_key()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}", "Content-Type": "application/json"}

    def verify_credentials(self) -> dict[str, Any]:
        if not self._secret:
            return {"ok": False, "message": "Flutterwave secret key is not set."}
        try:
            resp = requests.get(
                f"{self.BASE}/banks/NG",
                headers=self._headers(),
                timeout=settings.PAYMENT_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            return {"ok": False, "message": f"Could not reach Flutterwave: {exc}"}
        if resp.status_code == 401:
            return {"ok": False, "message": "Flutterwave rejected the secret key (401)."}
        if resp.status_code >= 400:
            return {"ok": False, "message": f"Flutterwave returned {resp.status_code}."}
        msg = "Flutterwave secret key is valid."
        if not config.flutterwave_secret_hash():
            msg += " Warning: webhook secret hash is not set."
        return {"ok": True, "message": msg}

    def create_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
        email: str,
        redirect_url: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not self._secret:
            raise PaymentError("Flutterwave secret key is not configured.")
        payload = {
            "tx_ref": reference,
            "amount": str(amount),
            "currency": currency.upper(),
            "redirect_url": redirect_url,
            "customer": {"email": email or "customer@example.com"},
            "meta": metadata,
        }
        try:
            resp = requests.post(
                f"{self.BASE}/payments",
                json=payload,
                headers=self._headers(),
                timeout=settings.PAYMENT_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise PaymentError(f"Flutterwave request failed: {exc}") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400 or body.get("status") != "success":
            raise PaymentError(f"Flutterwave init failed: {body.get('message', resp.text[:200])}")
        return {
            "intent_id": reference,
            "status": "pending",
            "authorization_url": body["data"]["link"],
        }

    def verify_signature(self, *, payload: bytes, signature: str) -> bool:
        secret_hash = config.flutterwave_secret_hash()
        if not secret_hash:
            return False
        return hmac.compare_digest(secret_hash, signature or "")

    def parse_event(self, payload: bytes) -> dict[str, Any]:
        body = json.loads(payload.decode() or "{}")
        data = body.get("data", {}) or {}
        succeeded = data.get("status") == "successful"
        return {
            "event_id": str(data.get("id", "")),
            "type": body.get("event", ""),
            "intent_id": data.get("tx_ref", ""),
            "status": "succeeded" if succeeded else data.get("status", ""),
        }

    def verify_transaction(self, *, reference: str, txn_id: str) -> dict[str, Any] | None:
        # Flutterwave recommends verifying by the gateway transaction id (data.id
        # from the webhook), falling back to the reference if id is absent.
        if txn_id:
            url = f"{self.BASE}/transactions/{txn_id}/verify"
            params: dict[str, str] | None = None
        else:
            url = f"{self.BASE}/transactions/verify_by_reference"
            params = {"tx_ref": reference}
        try:
            resp = requests.get(
                url, params=params, headers=self._headers(), timeout=settings.PAYMENT_HTTP_TIMEOUT
            )
        except requests.RequestException as exc:
            raise PaymentError(f"Flutterwave verify failed: {exc}") from exc
        body = resp.json() if resp.content else {}
        data = body.get("data", {}) or {}
        return {
            "status": "succeeded" if data.get("status") == "successful" else data.get("status", ""),
            "amount": Decimal(str(data.get("amount", "0"))),
            "currency": (data.get("currency") or "").upper(),
            "reference": data.get("tx_ref", ""),
        }


_PROVIDERS: dict[str, type[PaymentProvider]] = {
    "mock": MockProvider,
    "paystack": PaystackProvider,
    "flutterwave": FlutterwaveProvider,
}


def get_payment_provider() -> PaymentProvider:
    return _PROVIDERS.get(config.provider_name(), MockProvider)()
