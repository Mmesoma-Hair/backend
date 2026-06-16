from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User


@receiver(post_save, sender=User)
def ensure_profile(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    if created:
        Profile.objects.get_or_create(user=instance)
