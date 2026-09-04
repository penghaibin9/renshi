import base.encrypted_fields
from django.db import migrations


def encrypt_existing(apps, schema_editor):
    model = apps.get_model("base", "DynamicEmailConfiguration")
    for instance in model.objects.all().only("pk", "password").iterator():
        if instance.password:
            instance.save(update_fields=["password"])


class Migration(migrations.Migration):
    dependencies = [("base", "0011_alter_companyleaves_options_and_more")]

    operations = [
        migrations.AlterField(
            model_name="dynamicemailconfiguration",
            name="password",
            field=base.encrypted_fields.EncryptedTextField(
                null=True, verbose_name="Email Authentication Password"
            ),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
