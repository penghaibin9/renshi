import uuid

from django.db import migrations, models


PARTICIPANT_CHOICES = [
    ("PENDING", "Pending"),
    ("RUNNING", "Running"),
    ("SUCCESS", "Success"),
    ("FAILED", "Failed"),
    ("UNAVAILABLE", "Unavailable"),
    ("NOT_REQUIRED", "Not required"),
]


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0002_exit_effect_pending")]

    operations = [
        migrations.CreateModel(
            name="ExitEffect",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("case_id", models.UUIDField(db_index=True)),
                ("effect_version", models.PositiveIntegerField(default=1)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("correlation_id", models.CharField(blank=True, default="", max_length=128)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("APPLYING", "Applying"), ("SUCCESS", "Success"), ("PARTIAL_FAILED", "Partial failed"), ("FAILED", "Failed")], db_index=True, default="PENDING", max_length=20)),
                ("hr03_status", models.CharField(choices=PARTICIPANT_CHOICES, default="PENDING", max_length=16)),
                ("hr03_receipt_json", models.JSONField(blank=True, default=dict)),
                ("hr14_status", models.CharField(choices=PARTICIPANT_CHOICES, default="NOT_REQUIRED", max_length=16)),
                ("hr14_receipt_json", models.JSONField(blank=True, default=dict)),
                ("iam_status", models.CharField(choices=PARTICIPANT_CHOICES, default="NOT_REQUIRED", max_length=16)),
                ("iam_receipt_json", models.JSONField(blank=True, default=dict)),
                ("settlement_status", models.CharField(choices=PARTICIPANT_CHOICES, default="NOT_REQUIRED", max_length=16)),
                ("settlement_receipt_json", models.JSONField(blank=True, default=dict)),
                ("archive_status", models.CharField(choices=PARTICIPANT_CHOICES, default="NOT_REQUIRED", max_length=16)),
                ("archive_receipt_json", models.JSONField(blank=True, default=dict)),
                ("last_error", models.TextField(blank=True, default="")),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("reconciled_at", models.DateTimeField(blank=True, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
            ],
            options={"db_table": "hr16_exit_effect"},
        ),
        migrations.AddConstraint(
            model_name="exiteffect",
            constraint=models.UniqueConstraint(fields=("tenant_id", "idempotency_key"), name="uq_hr16_effect_idem"),
        ),
        migrations.AddConstraint(
            model_name="exiteffect",
            constraint=models.UniqueConstraint(fields=("tenant_id", "case_id", "effect_version"), name="uq_hr16_effect_case_ver"),
        ),
        migrations.AddIndex(
            model_name="exiteffect",
            index=models.Index(fields=["tenant_id", "case_id", "status"], name="idx_hr16_effect_case"),
        ),
        migrations.AddIndex(
            model_name="exiteffect",
            index=models.Index(fields=["tenant_id", "status", "reconciled_at"], name="idx_hr16_effect_recon"),
        ),
    ]
