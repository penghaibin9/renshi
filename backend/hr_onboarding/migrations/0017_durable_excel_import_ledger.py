import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_onboarding", "0016_material_download_ticket"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrOnboardingImportJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True)),
                ("uploaded_by", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("confirmed_by", models.BigIntegerField(blank=True, db_index=True, null=True)),
                ("file_name", models.CharField(max_length=255)),
                ("source_sha256", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("VALIDATING", "Validating"), ("VALIDATION_FAILED", "Validation failed"), ("READY_TO_COMMIT", "Ready to commit"), ("COMMITTING", "Committing"), ("COMPLETED", "Completed"), ("FAILED", "Failed")], db_index=True, max_length=24)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("error_count", models.PositiveIntegerField(default=0)),
                ("created_count", models.PositiveIntegerField(default=0)),
                ("skipped_count", models.PositiveIntegerField(default=0)),
                ("failed_count", models.PositiveIntegerField(default=0)),
                ("result_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("commit_started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "hr05_import_job",
                "indexes": [
                    models.Index(fields=["tenant_id", "status", "created_at"], name="idx_hr05_import_tenant_status"),
                    models.Index(fields=["tenant_id", "source_sha256"], name="idx_hr05_import_source_hash"),
                ],
            },
        ),
        migrations.CreateModel(
            name="HrOnboardingImportRow",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True)),
                ("row_no", models.PositiveIntegerField()),
                ("payload_json", models.JSONField(default=dict)),
                ("status", models.CharField(choices=[("VALID", "Valid"), ("INVALID", "Invalid"), ("CREATED", "Created"), ("SKIPPED", "Skipped"), ("FAILED", "Failed")], db_index=True, max_length=16)),
                ("error_json", models.JSONField(blank=True, default=list)),
                ("result_ref", models.CharField(blank=True, default="", max_length=128)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="rows", to="hr_onboarding.hronboardingimportjob")),
            ],
            options={
                "db_table": "hr05_import_row",
                "indexes": [
                    models.Index(fields=["tenant_id", "job", "status"], name="idx_hr05_import_row_status"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("tenant_id", "job", "row_no"), name="uq_hr05_import_row_no"),
                ],
            },
        ),
    ]
