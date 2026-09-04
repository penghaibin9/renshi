import base.encrypted_fields
from django.db import migrations


def encrypt_existing(apps, schema_editor):
    model = apps.get_model("horilla_ldap", "LDAPSettings")
    for instance in model.objects.all().only("pk", "bind_password").iterator():
        if instance.bind_password:
            instance.save(update_fields=["bind_password"])


class Migration(migrations.Migration):
    dependencies = [("horilla_ldap", "0002_alter_ldapsettings_options")]

    operations = [
        migrations.AlterField(
            model_name="ldapsettings",
            name="bind_password",
            field=base.encrypted_fields.EncryptedTextField(),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
