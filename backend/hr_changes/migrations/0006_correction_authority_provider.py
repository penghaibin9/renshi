from django.db import migrations, models


def backfill_create_keys(apps, schema_editor):
    correction = apps.get_model("hr_changes", "HrChangeCorrection")
    for row in correction.objects.filter(create_idempotency_key__isnull=True).iterator():
        row.create_idempotency_key = f"legacy-{row.id}"
        row.create_request_hash = f"legacy-{row.id}"
        row.save(update_fields=["create_idempotency_key", "create_request_hash"])


class Migration(migrations.Migration):
    dependencies = [("hr_changes", "0005_hrchangeauthoritymode")]

    operations = [
        migrations.AddField(
            model_name="hrchangecorrection",
            name="applied_fields_json",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="apply_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="apply_idempotency_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="authority_snapshot_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="authority_version",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="create_idempotency_key",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="create_request_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="evidence_material_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="provider_case_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="provider_case_version",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hrchangecorrection",
            name="provider_code",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.RunPython(backfill_create_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="hrchangecorrection",
            name="create_idempotency_key",
            field=models.CharField(max_length=64),
        ),
        migrations.AddConstraint(
            model_name="hrchangecorrection",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "create_idempotency_key"),
                name="uniq_hr_change_correction_create_key",
            ),
        ),
    ]
