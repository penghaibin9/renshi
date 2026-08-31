from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_payroll", "0004_benefit_pension_authority"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollperiod",
            name="time_source_snapshot_json",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
