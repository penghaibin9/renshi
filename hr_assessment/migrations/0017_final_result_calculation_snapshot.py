from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_assessment", "0016_result_revision_chain_seal"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrfinalassessmentresult",
            name="calculation_snapshot_json",
            field=models.JSONField(default=dict, verbose_name="服务端计算依据快照"),
        ),
        migrations.AddField(
            model_name="hrfinalassessmentresult",
            name="calculation_hash",
            field=models.CharField(
                default="",
                max_length=64,
                verbose_name="计算依据哈希",
            ),
        ),
    ]
