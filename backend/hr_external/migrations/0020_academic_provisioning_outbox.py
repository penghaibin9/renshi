import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_external", "0019_provisioning_delivery_receipt")]

    operations = [
        migrations.CreateModel(
            name="HrExternalAcademicProvisioningRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True)),
                ("operation", models.CharField(choices=[("ACTIVATE", "Activate"), ("DEACTIVATE", "Deactivate")], max_length=16)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("SUCCESS", "Success"), ("FAILED_RETRYABLE", "Failed Retryable"), ("FAILED", "Failed"), ("SKIPPED", "Skipped")], db_index=True, default="PENDING", max_length=24)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("external_ref", models.CharField(blank=True, default="", max_length=128)),
                ("provider_receipt_json", models.JSONField(blank=True, default=dict)),
                ("retry_count", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("error_message", models.CharField(blank=True, default="", max_length=512)),
                ("version", models.BigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("academic_identity_id", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="provisioning_requests", to="hr_external.hrexternalacademicidentity")),
            ],
        ),
        migrations.AddConstraint(
            model_name="hrexternalacademicprovisioningrequest",
            constraint=models.UniqueConstraint(fields=("tenant_id", "idempotency_key"), name="uniq_hr_external_academic_req_idem"),
        ),
        migrations.AddConstraint(
            model_name="hrexternalacademicprovisioningrequest",
            constraint=models.CheckConstraint(condition=models.Q(version__gte=1), name="hex_academic_req_version_gte_1"),
        ),
        migrations.AddIndex(
            model_name="hrexternalacademicprovisioningrequest",
            index=models.Index(fields=["tenant_id", "status", "next_attempt_at"], name="hex_academic_req_due_idx"),
        ),
    ]
