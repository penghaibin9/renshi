import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_title", "0003_title_material_snapshot")]

    operations = [
        migrations.AlterModelOptions(
            name="titlepolicyversion",
            options={
                "permissions": [
                    ("hr.title.view", "查看 HR13 职称评审工作区"),
                    ("hr.title.review", "执行 HR13 资格审查"),
                ],
            },
        ),
        migrations.CreateModel(
            name="TitleQualificationDecision",
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
                ("decision_no", models.CharField(max_length=64)),
                ("application_case_id", models.UUIDField()),
                ("attempt_no", models.PositiveIntegerField()),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("ELIGIBLE", "Eligible"),
                            ("RETURNED", "Returned for correction"),
                            ("REJECTED", "Rejected"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("reason_code", models.CharField(blank=True, default="", max_length=64)),
                ("reason", models.TextField(blank=True, default="")),
                ("decided_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "hr13_title_qualification_decision"},
        ),
        migrations.AddConstraint(
            model_name="titlequalificationdecision",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "decision_no"),
                name="uq_hr13_qualification_tenant_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="titlequalificationdecision",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr13_qualification_case_attempt",
            ),
        ),
        migrations.AddIndex(
            model_name="titlequalificationdecision",
            index=models.Index(
                fields=["tenant_id", "application_case_id", "decision"],
                name="idx_hr13_qualification_case",
            ),
        ),
    ]
