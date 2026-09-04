import base.encrypted_fields
from django.db import migrations


SECRET_FIELDS = ("meta_token", "meta_webhook_token")


def encrypt_existing(apps, schema_editor):
    model = apps.get_model("whatsapp", "WhatsappCredientials")
    for instance in model.objects.all().only("pk", *SECRET_FIELDS).iterator():
        populated = [name for name in SECRET_FIELDS if getattr(instance, name)]
        if populated:
            instance.save(update_fields=populated)


class Migration(migrations.Migration):
    dependencies = [("whatsapp", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="whatsappcredientials",
            name="meta_token",
            field=base.encrypted_fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="whatsappcredientials",
            name="meta_webhook_token",
            field=base.encrypted_fields.EncryptedTextField(
                help_text="This token is used to connect webhook to the server",
                verbose_name="Webhook Token",
            ),
        ),
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
