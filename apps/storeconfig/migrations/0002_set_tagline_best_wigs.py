from django.db import migrations

TAGLINE = "Best Wigs You can Trust"


def set_tagline(apps, schema_editor) -> None:
    Setting = apps.get_model("storeconfig", "Setting")
    Setting.objects.update_or_create(
        key="store.tagline",
        defaults={"section": "identity", "value": TAGLINE},
    )


def noop(apps, schema_editor) -> None:
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("storeconfig", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(set_tagline, noop),
    ]
