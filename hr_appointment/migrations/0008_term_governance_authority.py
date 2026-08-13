import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0007_publicity_objection_authority")]

    operations = [
        migrations.CreateModel(
            name="AppointmentTerm",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("term_no", models.CharField(max_length=64)),
                ("appointment_fact_id", models.UUIDField()),
                ("person_id", models.UUIDField()),
                ("position_instance_id", models.PositiveBigIntegerField()),
                ("level_code", models.CharField(blank=True, default="", max_length=64)),
                ("policy_version_id", models.UUIDField()),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("EXPIRING", "Expiring"), ("RENEWAL_IN_PROGRESS", "Renewal in progress"), ("RENEWED", "Renewed"), ("EXPIRED", "Expired"), ("TERMINATED", "Terminated"), ("REAPPOINTMENT_REQUIRED", "Reappointment required")], db_index=True, default="ACTIVE", max_length=32)),
                ("renewal_due_at", models.DateField(blank=True, null=True)),
                ("supersedes_term_id", models.UUIDField(blank=True, null=True)),
                ("source_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("version", models.PositiveBigIntegerField(default=1)),
            ],
            options={
                "db_table": "hr14_appointment_term",
                "permissions": [("hr.appointment.term", "维护 HR14 聘期与变更治理")],
            },
        ),
        migrations.CreateModel(
            name="AppointmentRenewalCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("renewal_no", models.CharField(max_length=64)),
                ("source_term_id", models.UUIDField()),
                ("attempt_no", models.PositiveIntegerField()),
                ("policy_version_id", models.UUIDField()),
                ("route", models.CharField(choices=[("DIRECT_RENEWAL", "Direct renewal"), ("TERM_ASSESSMENT", "Renewal after term assessment"), ("REAPPOINTMENT", "New competition/reappointment")], max_length=32)),
                ("hr12_term_result_ref", models.CharField(blank=True, default="", max_length=160)),
                ("proposed_effective_from", models.DateField()),
                ("proposed_effective_to", models.DateField(blank=True, null=True)),
                ("proposed_level_code", models.CharField(blank=True, default="", max_length=64)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ASSESSMENT_REQUIRED", "Assessment required"), ("READY", "Ready for decision"), ("APPROVED", "Approved; new result/term required"), ("REJECTED", "Rejected"), ("CANCELLED", "Cancelled"), ("APPLIED", "Successor appointment applied"), ("REAPPOINTMENT_REQUIRED", "Reappointment required")], db_index=True, default="DRAFT", max_length=32)),
                ("decision_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("successor_fact_id", models.UUIDField(blank=True, null=True)),
                ("successor_term_id", models.UUIDField(blank=True, null=True)),
                ("decided_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr14_appointment_renewal_case"},
        ),
        migrations.CreateModel(
            name="AppointmentChangeCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("change_no", models.CharField(max_length=64)),
                ("source_term_id", models.UUIDField()),
                ("attempt_no", models.PositiveIntegerField()),
                ("change_type", models.CharField(choices=[("PROMOTION", "Higher appointment"), ("DOWNGRADE", "Lower appointment"), ("TRANSFER", "Position transfer"), ("TERMINATION", "Appointment termination"), ("CORRECTION", "Formal correction")], max_length=24)),
                ("policy_version_id", models.UUIDField()),
                ("target_position_instance_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("target_level_code", models.CharField(blank=True, default="", max_length=64)),
                ("effective_date", models.DateField()),
                ("reason", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("REVIEW_REQUIRED", "Formal review required"), ("APPROVED", "Approved; downstream effect required"), ("REJECTED", "Rejected"), ("CANCELLED", "Cancelled"), ("APPLIED", "Successor appointment applied"), ("REAPPOINTMENT_REQUIRED", "New competition required")], db_index=True, default="DRAFT", max_length=32)),
                ("decision_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("successor_fact_id", models.UUIDField(blank=True, null=True)),
                ("successor_term_id", models.UUIDField(blank=True, null=True)),
                ("decided_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr14_appointment_change_case"},
        ),
        migrations.AddConstraint(
            model_name="appointmentterm",
            constraint=models.UniqueConstraint(fields=("tenant_id", "term_no"), name="uq_hr14_term_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="appointmentterm",
            constraint=models.UniqueConstraint(fields=("tenant_id", "appointment_fact_id"), name="uq_hr14_term_fact"),
        ),
        migrations.AddConstraint(
            model_name="appointmentterm",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", models.F("effective_from")), _connector="OR"), name="ck_hr14_term_effective_range"),
        ),
        migrations.AddIndex(
            model_name="appointmentterm",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr14_term_person_status"),
        ),
        migrations.AddIndex(
            model_name="appointmentterm",
            index=models.Index(fields=["tenant_id", "renewal_due_at", "status"], name="idx_hr14_term_due_status"),
        ),
        migrations.AddConstraint(
            model_name="appointmentrenewalcase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "renewal_no"), name="uq_hr14_renewal_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="appointmentrenewalcase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "source_term_id", "attempt_no"), name="uq_hr14_renewal_term_attempt"),
        ),
        migrations.AddConstraint(
            model_name="appointmentrenewalcase",
            constraint=models.CheckConstraint(condition=models.Q(("proposed_effective_to__isnull", True), ("proposed_effective_to__gt", models.F("proposed_effective_from")), _connector="OR"), name="ck_hr14_renewal_effective_range"),
        ),
        migrations.AddIndex(
            model_name="appointmentrenewalcase",
            index=models.Index(fields=["tenant_id", "source_term_id", "status"], name="idx_hr14_renewal_term_status"),
        ),
        migrations.AddConstraint(
            model_name="appointmentchangecase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "change_no"), name="uq_hr14_change_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="appointmentchangecase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "source_term_id", "attempt_no"), name="uq_hr14_change_term_attempt"),
        ),
        migrations.AddIndex(
            model_name="appointmentchangecase",
            index=models.Index(fields=["tenant_id", "source_term_id", "status"], name="idx_hr14_change_term_status"),
        ),
        migrations.AddIndex(
            model_name="appointmentchangecase",
            index=models.Index(fields=["tenant_id", "change_type", "status"], name="idx_hr14_change_type_status"),
        ),
    ]
