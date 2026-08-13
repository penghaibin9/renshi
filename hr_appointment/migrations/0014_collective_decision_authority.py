import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("hr_appointment", "0013_population_snapshot_authority"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppointmentCollectiveDecision",
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
                ("batch_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("position_instance_id", models.PositiveBigIntegerField()),
                (
                    "outcome",
                    models.CharField(
                        choices=[("APPROVED", "Approved"), ("REJECTED", "Rejected")],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("authority_ref", models.CharField(max_length=200)),
                ("decision_reason", models.TextField(blank=True, default="")),
                ("evidence_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("decided_at", models.DateTimeField()),
                (
                    "publicity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="collective_decision",
                        to="hr_appointment.appointmentpublicityrecord",
                    ),
                ),
            ],
            options={
                "db_table": "hr14_collective_decision",
                "permissions": [
                    ("hr.appointment.decision", "执行 HR14 集体审定并形成正式决定事实"),
                ],
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "application_case_id", "outcome"],
                        name="idx_hr14_collective_case",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "decision_no"),
                        name="uq_hr14_collective_decision_no",
                    ),
                    models.UniqueConstraint(
                        fields=("tenant_id", "publicity"),
                        name="uq_hr14_collective_publicity",
                    ),
                ],
            },
        ),
    ]
