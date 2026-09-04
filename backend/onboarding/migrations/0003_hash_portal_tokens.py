import hashlib

from django.db import migrations, models


PREFIX = "sha256$"


def hash_existing_tokens(apps, schema_editor):
    model = apps.get_model("onboarding", "OnboardingPortal")
    for instance in model.objects.all().only("pk", "token").iterator():
        value = str(instance.token or "")
        if not value or (value.startswith(PREFIX) and len(value) == 71):
            continue
        digest = hashlib.sha256(
            b"renshi:onboarding-portal:v1:" + value.encode("utf-8")
        ).hexdigest()
        model.objects.filter(pk=instance.pk).update(token=PREFIX + digest)


class Migration(migrations.Migration):
    dependencies = [("onboarding", "0002_onboardingtask_is_required")]

    operations = [
        migrations.AlterField(
            model_name="onboardingportal",
            name="token",
            field=models.CharField(db_index=True, max_length=71),
        ),
        migrations.RunPython(hash_existing_tokens, migrations.RunPython.noop),
    ]
