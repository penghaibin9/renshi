from django.db import migrations, models
import django.db.models.deletion


def backfill_legacy_batches(apps, schema_editor):
    Batch = apps.get_model("hr_time", "HrTimeCorrectionBatch")
    for batch in Batch.objects.all().iterator():
        batch.request_key = f"legacy-{batch.pk}"
        batch.requested_at = batch.created_at
        batch.requested_by_id = batch.approved_by_id
        batch.status = "APPLIED" if batch.after_snapshot_id else "APPROVED"
        batch.save(
            update_fields=["request_key", "requested_at", "requested_by", "status"]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("hr_time", "0011_shorten_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrtimecorrectionbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("REQUESTED", "待独立审批"),
                    ("APPROVED", "已批准重开"),
                    ("APPLIED", "更正已重新月结"),
                    ("REJECTED", "已拒绝"),
                ],
                db_index=True,
                default="REQUESTED",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="hrtimecorrectionbatch",
            name="request_key",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="hrtimecorrectionbatch",
            name="requested_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="horilla_auth.horillauser",
            ),
        ),
        migrations.AddField(
            model_name="hrtimecorrectionbatch",
            name="requested_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="hrtimecorrectionbatch",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_legacy_batches, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="hrtimecorrectionbatch",
            name="request_key",
            field=models.CharField(max_length=64),
        ),
        migrations.AlterField(
            model_name="hrtimecorrectionbatch",
            name="requested_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AddConstraint(
            model_name="hrtimecorrectionbatch",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "request_key"),
                name="uniq_hr11_reopen_request_key",
            ),
        ),
    ]
