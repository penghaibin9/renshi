import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MetricDefinitionVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("version_no", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(db_index=True, default="DRAFT", max_length=32)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("metric_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("value_type", models.CharField(max_length=32)),
                ("unit", models.CharField(blank=True, default="", max_length=32)),
                ("population_code", models.CharField(max_length=64)),
                ("expression", models.TextField()),
                ("source_domains", models.JSONField(default=list)),
                ("as_of_required", models.BooleanField(default=True)),
            ],
            options={"db_table": "hr18_metric_definition_version"},
        ),
        migrations.CreateModel(
            name="DataQualityFinding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("finding_no", models.CharField(max_length=64)),
                ("rule_code", models.CharField(max_length=64)),
                ("source_domain", models.CharField(max_length=16)),
                ("source_object_ref", models.CharField(max_length=128)),
                ("severity", models.CharField(choices=[("INFO", "Info"), ("WARNING", "Warning"), ("ERROR", "Error"), ("CRITICAL", "Critical")], db_index=True, default="WARNING", max_length=16)),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("ACKNOWLEDGED", "Acknowledged"), ("FIXED_AT_SOURCE", "Fixed at source"), ("DISMISSED", "Dismissed")], db_index=True, default="OPEN", max_length=24)),
                ("detected_at", models.DateTimeField()),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr18_data_quality_finding"},
        ),
        migrations.CreateModel(
            name="SubmissionSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("submission_no", models.CharField(max_length=64)),
                ("definition_code", models.CharField(max_length=64)),
                ("definition_version", models.PositiveIntegerField()),
                ("as_of_date", models.DateField()),
                ("scope_json", models.JSONField(default=dict)),
                ("payload_hash", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("VALIDATED", "Validated"), ("APPROVED", "Approved"), ("SUBMITTED", "Submitted"), ("ACCEPTED", "Accepted"), ("REJECTED", "Rejected"), ("CORRECTED", "Corrected")], db_index=True, default="DRAFT", max_length=16)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("receipt_ref", models.CharField(blank=True, default="", max_length=255)),
                ("parent_submission_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr18_submission_snapshot"},
        ),
        migrations.AddConstraint(
            model_name="metricdefinitionversion",
            constraint=models.UniqueConstraint(fields=("tenant_id", "metric_code", "version_no"), name="uq_hr18_metric_tenant_code_ver"),
        ),
        migrations.AddIndex(
            model_name="metricdefinitionversion",
            index=models.Index(fields=["tenant_id", "metric_code", "status"], name="idx_hr18_metric_tenant_status"),
        ),
        migrations.AddConstraint(
            model_name="dataqualityfinding",
            constraint=models.UniqueConstraint(fields=("tenant_id", "finding_no"), name="uq_hr18_finding_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="dataqualityfinding",
            index=models.Index(fields=["tenant_id", "source_domain", "status"], name="idx_hr18_finding_domain_status"),
        ),
        migrations.AddConstraint(
            model_name="submissionsnapshot",
            constraint=models.UniqueConstraint(fields=("tenant_id", "submission_no"), name="uq_hr18_submission_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="submissionsnapshot",
            index=models.Index(fields=["tenant_id", "definition_code", "status"], name="idx_hr18_submission_def_status"),
        ),
        migrations.AddIndex(
            model_name="submissionsnapshot",
            index=models.Index(fields=["tenant_id", "as_of_date"], name="idx_hr18_submission_asof"),
        ),
    ]
