# Generated for HR14 batch/quota authority hardening.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_appointment", "0004_appointment_view_permission")]

    operations = [
        migrations.CreateModel(
            name="AppointmentBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("version_no", models.PositiveIntegerField(default=1)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("batch_no", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("business_type", models.CharField(default="COMPETITIVE_APPOINTMENT", max_length=48)),
                ("policy_version_id", models.UUIDField()),
                ("target_categories_json", models.JSONField(blank=True, default=list)),
                ("target_levels_json", models.JSONField(blank=True, default=list)),
                ("application_from", models.DateTimeField(blank=True, null=True)),
                ("application_to", models.DateTimeField(blank=True, null=True)),
                ("publicity_from", models.DateTimeField(blank=True, null=True)),
                ("publicity_to", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("CONFIGURING", "Configuring"), ("PUBLISHED", "Published"), ("APPLICATION_OPEN", "Application open"), ("APPLICATION_CLOSED", "Application closed"), ("ELIGIBILITY_REVIEW", "Eligibility review"), ("REVIEWING", "Reviewing"), ("RANKING", "Ranking"), ("PROPOSED", "Proposed"), ("PUBLICITY", "Publicity"), ("FINALIZING", "Finalizing"), ("CLOSED", "Closed"), ("ARCHIVED", "Archived")], db_index=True, default="DRAFT", max_length=32)),
            ],
            options={
                "db_table": "hr14_appointment_batch",
                "indexes": [models.Index(fields=["tenant_id", "status", "batch_no"], name="idx_hr14_batch_tenant_status")],
                "constraints": [
                    models.UniqueConstraint(fields=("tenant_id", "batch_no"), name="uq_hr14_batch_tenant_no"),
                    models.CheckConstraint(condition=models.Q(("application_from__isnull", True), ("application_to__isnull", True), ("application_to__gt", models.F("application_from")), _connector="OR"), name="ck_hr14_batch_apply_range"),
                    models.CheckConstraint(condition=models.Q(("publicity_from__isnull", True), ("publicity_to__isnull", True), ("publicity_to__gt", models.F("publicity_from")), _connector="OR"), name="ck_hr14_batch_publicity_range"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AppointmentPositionSupplySnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("position_instance_id", models.PositiveBigIntegerField()),
                ("organization_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("category_code", models.CharField(blank=True, default="", max_length=64)),
                ("level_code", models.CharField(blank=True, default="", max_length=64)),
                ("authorized_fte", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("occupied_fte", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("reserved_fte", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("available_fte", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("structure_ratio_refs_json", models.JSONField(blank=True, default=list)),
                ("snapshot_at", models.DateTimeField()),
                ("source_version", models.CharField(blank=True, default="", max_length=64)),
                ("source_hash", models.CharField(blank=True, default="", max_length=64)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="position_supply_snapshots", to="hr_appointment.appointmentbatch")),
            ],
            options={
                "db_table": "hr14_position_supply_snapshot",
                "indexes": [models.Index(fields=["tenant_id", "batch", "category_code", "level_code"], name="idx_hr14_supply_batch_level")],
                "constraints": [
                    models.UniqueConstraint(fields=("tenant_id", "batch", "position_instance_id"), name="uq_hr14_supply_batch_position"),
                    models.CheckConstraint(condition=models.Q(("authorized_fte__gte", 0), ("occupied_fte__gte", 0), ("reserved_fte__gte", 0), ("available_fte__gte", 0)), name="ck_hr14_supply_non_negative"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AppointmentQuotaPool",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("scope_type", models.CharField(default="SCHOOL", max_length=32)),
                ("scope_org_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("category_code", models.CharField(max_length=64)),
                ("level_group_code", models.CharField(blank=True, default="", max_length=64)),
                ("exact_level_code", models.CharField(blank=True, default="", max_length=64)),
                ("authorized", models.PositiveIntegerField(default=0)),
                ("occupied", models.PositiveIntegerField(default=0)),
                ("reserved", models.PositiveIntegerField(default=0)),
                ("exception_quota", models.PositiveIntegerField(default=0)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="quota_pools", to="hr_appointment.appointmentbatch")),
            ],
            options={
                "db_table": "hr14_appointment_quota_pool",
                "indexes": [models.Index(fields=["tenant_id", "batch", "category_code", "exact_level_code"], name="idx_hr14_quota_batch_level")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "batch", "scope_type", "scope_org_id", "category_code", "level_group_code", "exact_level_code"), name="uq_hr14_quota_scope_level")],
            },
        ),
        migrations.CreateModel(
            name="AppointmentQuotaReservation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("units", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("RELEASED", "Released"), ("CONSUMED", "Consumed")], db_index=True, default="ACTIVE", max_length=16)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("application_case", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="quota_reservation", to="hr_appointment.appointmentapplicationcase")),
                ("quota_pool", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reservations", to="hr_appointment.appointmentquotapool")),
            ],
            options={
                "db_table": "hr14_appointment_quota_reservation",
                "indexes": [models.Index(fields=["tenant_id", "quota_pool", "status"], name="idx_hr14_quota_reservation")],
            },
        ),
    ]
