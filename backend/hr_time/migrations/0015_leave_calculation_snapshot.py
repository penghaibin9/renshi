from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_time", "0014_hr11_authority_database_seals"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrleaverequest",
            name="calculation_snapshot",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="冻结提交时采用的工作日历、排班和工作日明细，审批后不得重新解释。",
                verbose_name="请假时长计算快照",
            ),
        ),
    ]
