import base.encrypted_fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("whatsapp", "0002_encrypt_whatsapp_credentials")]

    operations = [
        migrations.AddField(
            model_name="whatsappcredientials",
            name="meta_app_secret",
            field=base.encrypted_fields.EncryptedTextField(
                blank=True,
                help_text="Required to verify signed webhook requests",
                null=True,
                verbose_name="Meta App Secret",
            ),
        ),
    ]
