import hashlib

from django.db import migrations, models


PREFIX = "sha256$"


def _replacement_digest(value, primary_key, attempt):
    payload = f"{value}:{primary_key}:{attempt}".encode("utf-8")
    return PREFIX + hashlib.sha256(
        b"renshi:bearer-token:v1:onboarding-portal-deduplicate:" + payload
    ).hexdigest()


def deduplicate_portal_tokens(apps, schema_editor):
    """Preserve the first link and invalidate ambiguous historical duplicates."""

    portal_model = apps.get_model("onboarding", "OnboardingPortal")
    seen = set()
    for portal in portal_model.objects.order_by("pk").only("pk", "token").iterator():
        value = str(portal.token or "")
        if value not in seen:
            seen.add(value)
            continue

        attempt = 0
        replacement = _replacement_digest(value, portal.pk, attempt)
        while replacement in seen:
            attempt += 1
            replacement = _replacement_digest(value, portal.pk, attempt)
        portal_model.objects.filter(pk=portal.pk).update(token=replacement)
        seen.add(replacement)


class Migration(migrations.Migration):
    dependencies = [("onboarding", "0003_hash_portal_tokens")]

    operations = [
        migrations.RunPython(
            deduplicate_portal_tokens,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="onboardingportal",
            name="token",
            field=models.CharField(max_length=71, unique=True),
        ),
    ]
