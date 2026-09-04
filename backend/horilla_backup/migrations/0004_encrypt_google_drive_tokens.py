import base.encrypted_fields
from django.db import migrations


SECRET_FIELDS = ("access_token", "refresh_token")


def encrypt_existing(apps, schema_editor):
    model = apps.get_model("horilla_backup", "GoogleDriveBackup")
    for instance in model.objects.all().only("pk", *SECRET_FIELDS).iterator():
        populated = [name for name in SECRET_FIELDS if getattr(instance, name)]
        if populated:
            instance.save(update_fields=populated)


class Migration(migrations.Migration):
    dependencies = [("horilla_backup", "0003_alter_googledrivebackup_gdrive_folder_id")]

    operations = [
        migrations.AlterField(
            model_name="googledrivebackup",
            name="access_token",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True,
                help_text="OAuth access token (automatically managed)",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="googledrivebackup",
            name="refresh_token",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True,
                help_text="OAuth refresh token (automatically managed)",
                null=True,
            ),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
