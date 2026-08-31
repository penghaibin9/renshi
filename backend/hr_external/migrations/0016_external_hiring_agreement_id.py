from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_external", "0015_projection_state_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrexternalhiringcase",
            name="agreement_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
