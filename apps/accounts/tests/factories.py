from __future__ import annotations

import factory

from apps.accounts.models import Role, User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Faker("name")
    role = Role.CUSTOMER

    @factory.post_generation
    def password(obj: User, create: bool, extracted: str | None, **kwargs: object) -> None:  # type: ignore[misc]
        obj.set_password(extracted or "Sup3rSecret!")
        if create:
            obj.save()
