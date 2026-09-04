from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("base", "0012_encrypt_dynamic_email_password")]

    operations = [
        migrations.AlterField(
            model_name="emaillog",
            name="company_id",
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=models.PROTECT,
                to="base.company",
            ),
        ),
    ]
