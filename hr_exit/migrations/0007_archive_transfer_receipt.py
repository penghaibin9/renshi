import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0006_exit_authority_permissions")]

    operations = [
        migrations.CreateModel(
            name="ArchiveTransferReceipt",
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
                ("transfer_no", models.CharField(max_length=64)),
                ("case_id", models.UUIDField(db_index=True)),
                ("person_id", models.UUIDField(db_index=True)),
                ("destination_type", models.CharField(blank=True, default="", max_length=64)),
                ("destination_name", models.CharField(max_length=200)),
                ("destination_address", models.CharField(blank=True, default="", max_length=500)),
                (
                    "transfer_method",
                    models.CharField(
                        choices=[
                            ("COURIER", "Courier"),
                            ("HAND_DELIVERY", "Hand delivery"),
                            ("SYSTEM_TRANSFER", "System transfer"),
                        ],
                        max_length=24,
                    ),
                ),
                ("tracking_no", models.CharField(blank=True, default="", max_length=128)),
                (
                    "archive_attachment_ref",
                    models.CharField(blank=True, default="", max_length=256),
                ),
                (
                    "receipt_attachment_ref",
                    models.CharField(blank=True, default="", max_length=256),
                ),
                ("operator_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("received_at", models.DateTimeField(blank=True, null=True)),
                ("received_by", models.CharField(blank=True, default="", max_length=200)),
                ("return_reason", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("SENT", "Sent"),
                            ("RECEIVED", "Received"),
                            ("RETURNED", "Returned"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        db_index=True,
                        default="DRAFT",
                        max_length=16,
                    ),
                ),
                ("supersedes_receipt_id", models.UUIDField(blank=True, null=True)),
            ],
            options={
                "db_table": "hr16_archive_transfer_receipt",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "transfer_no"),
                        name="uq_hr16_archive_transfer_no",
                    ),
                    models.UniqueConstraint(
                        fields=("tenant_id", "supersedes_receipt_id"),
                        name="uq_hr16_archive_supersede",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "case_id", "status"],
                        name="idx_hr16_archive_case",
                    ),
                    models.Index(
                        fields=["tenant_id", "person_id", "status"],
                        name="idx_hr16_archive_person",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="HrExitArchivePermissionMeta",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                )
            ],
            options={
                "managed": False,
                "permissions": (
                    (
                        "hr.exit.archive_transfer.view",
                        "HR16: View archive transfer receipts",
                    ),
                    (
                        "hr.exit.archive_transfer.manage",
                        "HR16: Manage archive transfer receipts",
                    ),
                ),
            },
        ),
    ]