"""Provider-agnostic payment integration.

``PaymentProvider`` is the seam every gateway implements (Stripe/Paystack/
Flutterwave later). ``MockProvider`` needs no external account: it mints
deterministic intent ids and HMAC-signs webhook payloads so the signature +
idempotency handling can be exercised end to end.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from django.conf import settings


class PaymentError(Exception):
    pass


class PaymentProvider(ABC):
    name = "base"

    @abstractmethod
    def create_intent(
        self, *, amount: Decimal, currency: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a payment intent; return at least {'intent_id', 'status'}."""

    @abstractmethod
    def verify_signature(self, *, payload: bytes, signature: str) -> bool:
        """Verify a webhook signature."""

    @abstractmethod
    def parse_event(self, payload: bytes) -> dict[str, Any]:
        """Parse a webhook body into {'event_id', 'type', 'intent_id', 'status'}."""


class MockProvider(PaymentProvider):
    name = "mock"

    @property
    def _secret(self) -> bytes:
        return settings.PAYMENT_WEBHOOK_SECRET.encode()

    def create_intent(
        self, *, amount: Decimal, currency: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "intent_id": f"mock_pi_{secrets.token_hex(8)}",
            "status": "requires_confirmation",
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


_PROVIDERS: dict[str, type[PaymentProvider]] = {"mock": MockProvider}


def get_payment_provider() -> PaymentProvider:
    name = getattr(settings, "PAYMENT_PROVIDER", "mock")
    return _PROVIDERS.get(name, MockProvider)()
