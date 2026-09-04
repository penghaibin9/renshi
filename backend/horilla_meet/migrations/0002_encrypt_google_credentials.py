import base.encrypted_fields
from django.db import migrations


def encrypt_existing(apps, schema_editor):
    cloud = apps.get_model("horilla_meet", "GoogleCloudCredential")
    for instance in cloud.objects.all().only("pk", "client_secret").iterator():
        if instance.client_secret:
            instance.save(update_fields=["client_secret"])

    employee = apps.get_model("horilla_meet", "GoogleCredential")
    fields = ("client_secret", "refresh_token", "token")
    for instance in employee.objects.all().only("pk", *fields).iterator():
        populated = [name for name in fields if getattr(instance, name)]
        if populated:
            instance.save(update_fields=populated)


class Migration(migrations.Migration):
    dependencies = [("horilla_meet", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="googlecloudcredential",
            name="client_secret",
            field=base.encrypted_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="googlecredential",
            name="client_secret",
            field=base.encrypted_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="googlecredential",
            name="refresh_token",
            field=base.encrypted_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="googlecredential",
            name="token",
            field=base.encrypted_fields.EncryptedTextField(),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
