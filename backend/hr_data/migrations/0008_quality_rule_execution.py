import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_data", "0007_typed_asof_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataQualityRuleVersion",
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
                ("rule_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("source_domain", models.CharField(max_length=16)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("INFO", "Info"),
                            ("WARNING", "Warning"),
                            ("ERROR", "Error"),
                            ("CRITICAL", "Critical"),
                        ],
                        db_index=True,
                        default="WARNING",
                        max_length=16,
                    ),
                ),
                ("parameters_json", models.JSONField(blank=True, default=dict)),
                ("as_of_required", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "hr18_data_quality_rule_version",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "rule_code", "status"],
                        name="idx_hr18_quality_rule_status",
                    ),
                    models.Index(
                        fields=["tenant_id", "source_domain", "status"],
                        name="idx_hr18_quality_rule_domain",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "rule_code", "version_no"),
                        name="uq_hr18_quality_rule_ver",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DataQualityRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("run_no", models.CharField(max_length=64)),
                ("rule_code", models.CharField(max_length=64)),
                ("rule_version", models.PositiveIntegerField()),
                ("source_domain", models.CharField(max_length=16)),
                ("as_of_date", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("SUCCESS", "Execution completed"),
                            ("PARTIAL", "Execution partially completed"),
                            ("UNAVAILABLE", "Provider unavailable"),
                            ("ERROR", "Provider error"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("provider_version", models.CharField(blank=True, default="", max_length=64)),
                ("evidence_hash", models.CharField(blank=True, default="", max_length=64)),
                ("finding_count", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True, default="")),
                ("executed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "hr18_data_quality_run",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "rule_code", "status"],
                        name="idx_hr18_quality_run_rule",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "run_no"),
                        name="uq_hr18_quality_run_no",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="dataqualityfinding",
            name="quality_run_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dataqualityfinding",
            name="rule_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dataqualityfinding",
            name="finding_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dataqualityfinding",
            name="details_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name="dataqualityfinding",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "quality_run_id", "finding_fingerprint"),
                name="uq_hr18_finding_run_fingerprint",
            ),
        ),
        migrations.AddIndex(
            model_name="dataqualityfinding",
            index=models.Index(
                fields=["tenant_id", "quality_run_id", "status"],
                name="idx_hr18_finding_run_status",
            ),
        ),
    ]
