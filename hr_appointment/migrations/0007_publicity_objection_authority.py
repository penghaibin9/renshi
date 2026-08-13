import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0006_review_ranking_result")]

    operations = [
        migrations.AlterModelOptions(
            name="appointmentpolicyversion",
            options={
                "permissions": [
                    ("hr.appointment.view", "查看 HR14 岗位聘任工作区"),
                    ("hr.appointment.review", "执行 HR14 评议排序"),
                    ("hr.appointment.publicity", "维护 HR14 拟聘公示与异议"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AppointmentPublicityRecord",
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
                ("application_case_id", models.UUIDField()),
                ("ranking_result_id", models.UUIDField()),
                ("batch_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("position_instance_id", models.PositiveBigIntegerField()),
                ("attempt_no", models.PositiveIntegerField(default=1)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField()),
                ("notice_snapshot_json", models.JSONField(blank=True, default=dict)),
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
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                ("closed_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_reason", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "hr14_appointment_publicity"},
        ),
        migrations.CreateModel(
            name="AppointmentPublicityObjection",
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
                ("objection_no", models.CharField(max_length=64)),
                ("publicity_id", models.UUIDField(db_index=True)),
                ("submitter_ref", models.CharField(blank=True, default="", max_length=128)),
                ("content_summary", models.TextField()),
                ("evidence_refs_json", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RECEIVED", "Received"),
                            ("UNDER_REVIEW", "Under review"),
                            ("UPHELD", "Upheld"),
                            ("NOT_UPHELD", "Not upheld"),
                            ("WITHDRAWN", "Withdrawn"),
                        ],
                        db_index=True,
                        default="RECEIVED",
                        max_length=20,
                    ),
                ),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_note", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "hr14_appointment_publicity_objection"},
        ),
        migrations.AddConstraint(
            model_name="appointmentpublicityrecord",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "publicity_no"),
                name="uq_hr14_publicity_tenant_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointmentpublicityrecord",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr14_publicity_case_attempt",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointmentpublicityrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(("end_at__gt", models.F("start_at"))),
                name="ck_hr14_publicity_time_range",
            ),
        ),
        migrations.AddIndex(
            model_name="appointmentpublicityrecord",
            index=models.Index(
                fields=["tenant_id", "batch_no", "status"],
                name="idx_hr14_publicity_batch",
            ),
        ),
        migrations.AddIndex(
            model_name="appointmentpublicityrecord",
            index=models.Index(
                fields=["tenant_id", "application_case_id", "status"],
                name="idx_hr14_publicity_case",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointmentpublicityobjection",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "objection_no"),
                name="uq_hr14_objection_tenant_no",
            ),
        ),
        migrations.AddIndex(
            model_name="appointmentpublicityobjection",
            index=models.Index(
                fields=["tenant_id", "publicity_id", "status"],
                name="idx_hr14_objection_publicity",
            ),
        ),
    ]
