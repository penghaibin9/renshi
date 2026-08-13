import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0004_exit_view_permission")]

    operations = [
        migrations.AlterModelOptions(
            name="exitcase",
            options={
                "permissions": [
                    ("hr.exit.view", "查看 HR16 退休与离校工作区"),
                    ("hr.exit.handover", "维护 HR16 离校交接清单"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ExitHandoverItem",
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
                ("item_no", models.CharField(max_length=64)),
                ("case_id", models.UUIDField(db_index=True)),
                ("category_code", models.CharField(max_length=64)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("required", models.BooleanField(db_index=True, default=True)),
                ("owner_staff_id", models.UUIDField(blank=True, null=True)),
                ("due_date", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("COMPLETED", "Completed"),
                            ("WAIVED", "Waived"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("evidence_ref", models.CharField(blank=True, default="", max_length=256)),
                ("completed_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("waiver_reason", models.TextField(blank=True, default="")),
                ("supersedes_item_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr16_exit_handover_item"},
        ),
        migrations.AddConstraint(
            model_name="exithandoveritem",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "item_no"),
                name="uq_hr16_handover_tenant_no",
            ),
        ),
        migrations.AddIndex(
            model_name="exithandoveritem",
            index=models.Index(
                fields=["tenant_id", "case_id", "required", "status"],
                name="idx_hr16_handover_case_gate",
            ),
        ),
        migrations.AddIndex(
            model_name="exithandoveritem",
            index=models.Index(
                fields=["tenant_id", "owner_staff_id", "status"],
                name="idx_hr16_handover_owner",
            ),
        ),
    ]
