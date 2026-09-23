from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("hr_data", "0018_operational_snapshot_seals")]

    operations = [
        migrations.AddField(
            model_name="exchangejob",
            name="retry_of_job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="manual_retry_jobs",
                to="hr_data.exchangejob",
            ),
        ),
        migrations.AddField(
            model_name="exchangejob",
            name="manual_retry_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="exchangejob",
            name="manual_retry_by",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="exchangejob",
            index=models.Index(
                fields=["tenant_id", "retry_of_job"],
                name="idx_hr18_exchange_retry_of",
            ),
        ),
    ]
