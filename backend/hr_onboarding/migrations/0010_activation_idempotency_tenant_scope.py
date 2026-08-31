from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr_onboarding", "0009_auto_index_complete"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hractivationattempt",
            name="idempotency_key",
            field=models.CharField(max_length=128),
        ),
        migrations.AddConstraint(
            model_name="hractivationattempt",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uniq_hr05_activation_tenant_idem",
            ),
        ),
    ]
