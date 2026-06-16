"""Currency metadata and exchange-rate history.

Product prices are stored once in the base currency (configured in storeconfig);
display/charge amounts are derived by :func:`apps.currency.services.convert`.
``Currency`` rows are the source of truth for which currencies are active and
how their amounts round/format. ``ExchangeRate`` keeps history so a failed fetch
can fall back to the last good rate.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.common.models import TimeStampedModel


class Currency(TimeStampedModel):
    code = models.CharField(max_length=3, primary_key=True, help_text="ISO 4217, e.g. USD.")
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=8, default="$")
    decimal_places = models.PositiveSmallIntegerField(default=2)
    # Optional psychological rounding: round to the nearest multiple of this
    # increment (e.g. 1.00 → whole units), then if charm_pricing, end in .99.
    rounding_increment = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    charm_pricing = models.BooleanField(
        default=False, help_text="After rounding, end prices in .99 (e.g. 20 → 19.99)."
    )
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "code")
        verbose_name_plural = "currencies"

    def __str__(self) -> str:
        return self.code


class ExchangeRate(TimeStampedModel):
    """A fetched rate: 1 ``base`` = ``rate`` × ``quote``. History is retained."""

    base = models.CharField(max_length=3, db_index=True)
    quote = models.CharField(max_length=3, db_index=True)
    rate = models.DecimalField(max_digits=20, decimal_places=10)
    source = models.CharField(max_length=40, default="mock")
    fetched_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ("-fetched_at",)
        indexes = [models.Index(fields=["base", "quote", "-fetched_at"])]

    def __str__(self) -> str:
        return f"{self.base}->{self.quote} {self.rate} @ {self.fetched_at:%Y-%m-%d %H:%M}"
