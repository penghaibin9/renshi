import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0005_batch_quota_supply")]

    operations = [
        migrations.AlterModelOptions(
            name="appointmentpolicyversion",
            options={
                "permissions": [
                    ("hr.appointment.view", "查看 HR14 岗位聘任工作区"),
                    ("hr.appointment.review", "执行 HR14 评议排序"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AppointmentRankingResult",
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
                ("ranking_no", models.CharField(max_length=64)),
                ("application_case_id", models.UUIDField()),
                ("batch_no", models.CharField(max_length=64)),
                ("position_instance_id", models.PositiveBigIntegerField()),
                ("attempt_no", models.PositiveIntegerField()),
                ("total_score", models.DecimalField(decimal_places=4, max_digits=12)),
                ("rank_no", models.PositiveIntegerField()),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("SELECTED", "Selected"),
                            ("WAITLIST", "Waitlist"),
                            ("NOT_SELECTED", "Not selected"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("score_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("finalized_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("finalized_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "hr14_appointment_ranking_result"},
        ),
        migrations.AddConstraint(
            model_name="appointmentrankingresult",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "ranking_no"),
                name="uq_hr14_ranking_tenant_no",
            ),
        ),
        migrations.AddConstraint(
            model_name="appointmentrankingresult",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "application_case_id", "attempt_no"),
                name="uq_hr14_ranking_case_attempt",
            ),
        ),
        migrations.AddIndex(
            model_name="appointmentrankingresult",
            index=models.Index(
                fields=["tenant_id", "batch_no", "position_instance_id", "rank_no"],
                name="idx_hr14_ranking_batch_position",
            ),
        ),
    ]
