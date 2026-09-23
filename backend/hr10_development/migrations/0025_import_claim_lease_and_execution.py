from django.db import migrations, models
from django.db.models import Count


def deduplicate_existing_import_rows(apps, schema_editor):
    StagingRow = apps.get_model("hr10_development", "HrDevelopmentStagingRow")
    groups = (
        StagingRow.objects.exclude(import_job_id__isnull=True)
        .values("tenant_id", "import_job_id", "source_object_id")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
    )
    for group in groups.iterator():
        rows = list(
            StagingRow.objects.filter(
                tenant_id=group["tenant_id"],
                import_job_id=group["import_job_id"],
                source_object_id=group["source_object_id"],
            ).order_by("id")
        )
        target_ids = {row.target_id for row in rows if row.target_id is not None}
        if len(target_ids) > 1:
            raise RuntimeError(
                "HR10_STAGING_DUPLICATE_TARGET_CONFLICT:"
                f"tenant={group['tenant_id']},job={group['import_job_id']},source={group['source_object_id']}"
            )
        keep = next((row for row in rows if row.target_id is not None), rows[0])
        StagingRow.objects.filter(id__in=[row.id for row in rows if row.id != keep.id]).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("hr10_development", "0024_hrfurtherstudymilestone_writeback_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="hrdevelopmentimportjob",
            name="claim_token",
            field=models.CharField(blank=True, default="", editable=False, max_length=64, verbose_name="Worker claim token"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentimportjob",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name="Worker heartbeat at"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentimportjob",
            name="lease_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, editable=False, null=True, verbose_name="Worker lease expires at"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentstagingrow",
            name="executed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="导入执行时间"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentstagingrow",
            name="execution_status",
            field=models.CharField(db_index=True, default="PENDING", max_length=16, verbose_name="导入执行状态"),
        ),
        migrations.AddIndex(
            model_name="hrdevelopmentstagingrow",
            index=models.Index(fields=["tenant_id", "execution_status"], name="hr_dev_stg_tenant_exec_idx"),
        ),
        migrations.RunPython(deduplicate_existing_import_rows, noop_reverse),
        migrations.AddConstraint(
            model_name="hrdevelopmentstagingrow",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "import_job_id", "source_object_id"),
                name="uniq_hr10_staging_import_row",
            ),
        ),
    ]
