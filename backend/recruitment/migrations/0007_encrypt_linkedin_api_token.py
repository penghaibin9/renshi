import base.encrypted_fields
from django.db import migrations


def encrypt_existing(apps, schema_editor):
    model = apps.get_model("recruitment", "LinkedInAccount")
    for instance in model.objects.all().only("pk", "api_token").iterator():
        if instance.api_token:
            instance.save(update_fields=["api_token"])


class Migration(migrations.Migration):
    dependencies = [
        (
            "recruitment",
            "0006_alter_rejectreason_options_alter_skillzone_options_and_more",
        )
    ]

    operations = [
        migrations.AlterField(
            model_name="linkedinaccount",
            name="api_token",
            field=base.encrypted_fields.EncryptedTextField(verbose_name="API Token"),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
