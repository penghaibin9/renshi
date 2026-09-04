import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_exit", "0012_retirement_cohort_policy"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrExitEvidenceAccessAudit",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("subject_type", models.CharField(max_length=32)),
                ("subject_id", models.UUIDField(db_index=True)),
                ("evidence_role", models.CharField(max_length=32)),
                ("storage_key_hash", models.CharField(max_length=64)),
                ("purpose", models.CharField(max_length=500)),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("request_id", models.CharField(blank=True, default="", max_length=128)),
            ],
            options={
                "db_table": "hr16_evidence_access_audit",
                "base_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "subject_type", "subject_id", "created_at"],
                        name="idx_hr16_evid_audit_subject",
                    ),
                    models.Index(
                        fields=["tenant_id", "actor_user_id", "created_at"],
                        name="idx_hr16_evid_audit_actor",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(storage_key_hash__regex=r"^[0-9a-f]{64}$"),
                        name="ck_hr16_evid_audit_hash",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(purpose__gt=""),
                        name="ck_hr16_evid_audit_purpose",
                    ),
                ],
            },
        ),
    ]
