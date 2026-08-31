import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_title", "0005_expert_review_authority")]

    operations = [
        migrations.AlterModelOptions(
            name="titlepolicyversion",
            options={
                "permissions": [
                    ("hr.title.view", "查看 HR13 职称评审工作区"),
                    ("hr.title.review", "执行 HR13 资格审查"),
                    ("hr.title.panel", "维护 HR13 专家评议与表决"),
                    ("hr.title.publicity", "维护 HR13 公示与异议复核"),
                ],
            },
        ),
        migrations.CreateModel(
            name="TitlePublicityRecord",
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
                ("publicity_no", models.CharField(max_length=64)),
                ("application_case_id", models.UUIDField(db_index=True)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField()),
                ("content_snapshot_json", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("OPEN", "Open"),
                            ("CLOSED", "Closed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        db_index=True,
                        default="OPEN",
                        max_length=16,
                    ),
                ),
                ("opened_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("closed_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_title_publicity_record"},
        ),
        migrations.CreateModel(
            name="TitleAppealRecord",
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
                ("appeal_no", models.CharField(max_length=64)),
                ("publicity_id", models.UUIDField(db_index=True)),
                ("application_case_id", models.UUIDField(db_index=True)),
                ("appellant_ref", models.CharField(blank=True, default="", max_length=128)),
                ("reason", models.TextField()),
                ("evidence_json", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("OPEN", "Open"),
                            ("REJECTED", "Rejected"),
                            ("UPHELD", "Upheld"),
                            ("WITHDRAWN", "Withdrawn"),
                        ],
                        db_index=True,
                        default="OPEN",
                        max_length=16,
                    ),
                ),
                ("resolution", models.TextField(blank=True, default="")),
                ("resolved_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_title_appeal_record"},
        ),
        migrations.AddConstraint(
            model_name="titlepublicityrecord",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "publicity_no"),
                name="uq_hr13_publicity_tenant_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="titlepublicityrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("end_at__gt", models.F("start_at"))),
                name="ck_hr13_publicity_time_range",
            ),
        ),
        migrations.AddIndex(
            model_name="titlepublicityrecord",
            index=models.Index(
                fields=["tenant_id", "application_case_id", "status"],
                name="idx_hr13_publicity_case",
            ),
        ),
        migrations.AddConstraint(
            model_name="titleappealrecord",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "appeal_no"),
                name="uq_hr13_appeal_tenant_no",
            ),
        ),
        migrations.AddIndex(
            model_name="titleappealrecord",
            index=models.Index(
                fields=["tenant_id", "publicity_id", "status"],
                name="idx_hr13_appeal_publicity",
            ),
        ),
    ]
