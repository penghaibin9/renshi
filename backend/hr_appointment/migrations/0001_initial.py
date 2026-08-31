import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AppointmentPolicyVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("version_no", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(db_index=True, default="DRAFT", max_length=32)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("policy_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("position_category", models.CharField(blank=True, default="", max_length=64)),
                ("level_code", models.CharField(blank=True, default="", max_length=64)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
            ],
            options={"db_table": "hr14_appointment_policy_version"},
        ),
        migrations.CreateModel(
            name="AppointmentApplicationCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("case_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("policy_version_id", models.UUIDField()),
                ("position_instance_id", models.UUIDField()),
                ("batch_no", models.CharField(max_length=64)),
                ("requested_level_code", models.CharField(blank=True, default="", max_length=64)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("RETURNED", "Returned for correction"), ("ELIGIBLE", "Eligibility passed"), ("REJECTED", "Rejected"), ("WITHDRAWN", "Withdrawn"), ("UNDER_REVIEW", "Under review"), ("PROPOSED", "Proposed appointment"), ("PUBLICITY", "Publicity"), ("EFFECTIVE", "Effective"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=32)),
            ],
            options={"db_table": "hr14_appointment_application_case"},
        ),
        migrations.CreateModel(
            name="PositionAppointmentFact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("appointment_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("position_instance_id", models.UUIDField()),
                ("application_case_id", models.UUIDField()),
                ("level_code", models.CharField(blank=True, default="", max_length=64)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("EFFECTIVE", "Effective"), ("REVISED", "Revised"), ("ENDED", "Ended"), ("REVOKED", "Revoked")], db_index=True, default="EFFECTIVE", max_length=16)),
                ("supersedes_fact_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr14_position_appointment_fact"},
        ),
        migrations.AddConstraint(
            model_name="appointmentpolicyversion",
            constraint=models.UniqueConstraint(fields=("tenant_id", "policy_code", "version_no"), name="uq_hr14_policy_tenant_code_ver"),
        ),
        migrations.AddConstraint(
            model_name="appointmentpolicyversion",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", models.F("effective_from")), _connector="OR"), name="ck_hr14_policy_effective_range"),
        ),
        migrations.AddConstraint(
            model_name="appointmentapplicationcase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr14_case_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="appointmentapplicationcase",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr14_case_tenant_person"),
        ),
        migrations.AddIndex(
            model_name="appointmentapplicationcase",
            index=models.Index(fields=["tenant_id", "batch_no", "status"], name="idx_hr14_case_tenant_batch"),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.UniqueConstraint(fields=("tenant_id", "appointment_no"), name="uq_hr14_fact_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", models.F("effective_from")), _connector="OR"), name="ck_hr14_fact_effective_range"),
        ),
        migrations.AddIndex(
            model_name="positionappointmentfact",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr14_fact_tenant_person"),
        ),
        migrations.AddIndex(
            model_name="positionappointmentfact",
            index=models.Index(fields=["tenant_id", "position_instance_id", "status"], name="idx_hr14_fact_tenant_position"),
        ),
    ]
