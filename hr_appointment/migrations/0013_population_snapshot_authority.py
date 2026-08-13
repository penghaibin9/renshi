import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("hr_appointment", "0012_workflow_permissions"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppointmentPopulationSnapshot",
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
                ("as_of_date", models.DateField()),
                ("snapshot_at", models.DateTimeField()),
                ("source_domain", models.CharField(default="HR03", max_length=32)),
                (
                    "source_version",
                    models.CharField(
                        default="hr03-employment-assignment-v1", max_length=64
                    ),
                ),
                ("criteria_json", models.JSONField(blank=True, default=dict)),
                ("member_count", models.PositiveIntegerField(default=0)),
                ("content_hash", models.CharField(max_length=64)),
                (
                    "batch",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="population_snapshot",
                        to="hr_appointment.appointmentbatch",
                    ),
                ),
            ],
            options={
                "db_table": "hr14_appointment_population_snapshot",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "as_of_date"],
                        name="idx_hr14_population_asof",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "batch"),
                        name="uq_hr14_population_batch",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AppointmentPopulationMemberSnapshot",
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
                ("person_id", models.UUIDField()),
                ("staff_id", models.UUIDField()),
                ("staff_category_code", models.CharField(blank=True, default="", max_length=32)),
                (
                    "employment_relationship_refs_json",
                    models.JSONField(blank=True, default=list),
                ),
                (
                    "primary_assignment_refs_json",
                    models.JSONField(blank=True, default=list),
                ),
                ("member_hash", models.CharField(max_length=64)),
                (
                    "snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="members",
                        to="hr_appointment.appointmentpopulationsnapshot",
                    ),
                ),
            ],
            options={
                "db_table": "hr14_appointment_population_member",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "snapshot", "person_id"],
                        name="idx_hr14_population_member",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "snapshot", "person_id"),
                        name="uq_hr14_population_member_person",
                    )
                ],
            },
        ),
    ]
