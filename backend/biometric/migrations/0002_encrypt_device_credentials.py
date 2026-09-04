import base.encrypted_fields
from django.db import migrations


SECRET_FIELDS = ("api_key", "api_secret", "api_token", "bio_password", "zk_password")


def encrypt_existing(apps, schema_editor):
    model = apps.get_model("biometric", "BiometricDevices")
    for instance in model.objects.all().only("pk", *SECRET_FIELDS).iterator():
        populated = [name for name in SECRET_FIELDS if getattr(instance, name)]
        if populated:
            instance.save(update_fields=populated)


class Migration(migrations.Migration):
    dependencies = [("biometric", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="biometricdevices",
            name="api_key",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True, null=True, verbose_name="API Key"
            ),
        ),
        migrations.AlterField(
            model_name="biometricdevices",
            name="api_secret",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True, null=True, verbose_name="API Secret"
            ),
        ),
        migrations.AlterField(
            model_name="biometricdevices",
            name="api_token",
            field=base.encrypted_fields.EncryptedTextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="biometricdevices",
            name="bio_password",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True, null=True, verbose_name="Password"
            ),
        ),
        migrations.AlterField(
            model_name="biometricdevices",
            name="zk_password",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True, default="0", null=True, verbose_name="Password"
            ),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
