"""Persistence for admin-overridden settings.

Only keys an admin has explicitly changed get a row here; everything else falls
back to the spec default in :mod:`apps.storeconfig.schema`. The value is stored
as JSON keyed by the spec name, so no migration is ever needed to add a knob.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from apps.common.models import TimeStampedModel


class Setting(TimeStampedModel):
    key = models.CharField(max_length=120, unique=True)
    section = models.CharField(max_length=60, db_index=True)
    # JSON wrapper so any type (bool/int/str/list/dict) round-trips losslessly.
    value = models.JSONField()

    class Meta:
        ordering = ("section", "key")

    def __str__(self) -> str:
        return self.key

    @property
    def raw_value(self) -> Any:
        return self.value
