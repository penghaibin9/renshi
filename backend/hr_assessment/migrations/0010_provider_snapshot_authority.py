from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_assessment", "0009_provider_snapshot_set"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrprovidersnapshotset",
            name="authority_json",
            field=models.JSONField(default=dict, verbose_name="政策与指标 Authority"),
        ),
    ]
