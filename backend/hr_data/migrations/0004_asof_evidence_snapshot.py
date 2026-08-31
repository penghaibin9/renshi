import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_data", "0003_population_dimension_definitions")]

    operations = [
        migrations.CreateModel(
            name="AsOfEvidenceSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("evidence_no", models.CharField(max_length=64)),
                ("definition_code", models.CharField(max_length=64)),
                ("definition_version", models.PositiveIntegerField()),
                ("as_of_date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("COMPLETE", "Complete"),
                            ("PARTIAL", "Partial"),
                            ("UNAVAILABLE", "Unavailable"),
                            ("ERROR", "Error"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("source_statuses_json", models.JSONField(default=dict)),
                ("blocked_domains_json", models.JSONField(blank=True, default=list)),
                ("provider_versions_json", models.JSONField(blank=True, default=dict)),
                ("evidence_hash", models.CharField(max_length=64)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "hr18_asof_evidence_snapshot"},
        ),
        migrations.AddConstraint(
            model_name="asofevidencesnapshot",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "evidence_no"),
                name="uq_hr18_asof_evidence_no",
            ),
        ),
        migrations.AddIndex(
            model_name="asofevidencesnapshot",
            index=models.Index(
                fields=["tenant_id", "definition_code", "as_of_date", "status"],
                name="idx_hr18_asof_def_status",
            ),
        ),
    ]
