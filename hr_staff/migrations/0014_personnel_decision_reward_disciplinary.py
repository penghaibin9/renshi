# Generated for HR03 PersonnelDecision + Reward/Disciplinary Authority.

import uuid

import django.db.models.deletion
from django.db import migrations, models


NEW_PERMISSIONS = (
    ("hr.staff.view", "HR Staff: View"),
    ("hr.staff.view_sensitive", "HR Staff: View Sensitive"),
    ("hr.staff.reveal_high_sensitive", "HR Staff: Reveal High Sensitive"),
    ("hr.staff.create", "HR Staff: Create"),
    ("hr.staff.edit_basic", "HR Staff: Edit Basic"),
    ("hr.staff.export", "HR Staff: Export"),
    ("hr.staff.export_sensitive", "HR Staff: Export Sensitive"),
    ("hr.staff.import", "HR Staff: Import"),
    ("hr.staff.assignment.view", "HR Staff: View Assignment"),
    ("hr.staff.assignment.correct", "HR Staff: Correct Assignment"),
    ("hr.staff.background.view", "HR Staff: View Background"),
    ("hr.staff.background.manage", "HR Staff: Manage Background"),
    ("hr.staff.material.view", "HR Staff: View Material"),
    ("hr.staff.material.upload", "HR Staff: Upload Material"),
    ("hr.staff.material.verify", "HR Staff: Verify Material"),
    ("hr.staff.material.download_sensitive", "HR Staff: Download Sensitive Material"),
    ("hr.staff.correction.view", "HR Staff: View Correction"),
    ("hr.staff.correction.create", "HR Staff: Create Correction"),
    ("hr.staff.correction.review", "HR Staff: Review Correction"),
    ("hr.staff.correction.approve_high_risk", "HR Staff: Approve High Risk Correction"),
    ("hr.staff.audit.view", "HR Staff: View Audit"),
    ("hr.staff.data_quality.manage", "HR Staff: Manage Data Quality"),
    ("hr.staff.personnel_decision.view", "HR Staff: View Personnel Decision"),
    ("hr.staff.personnel_decision.manage", "HR Staff: Manage Personnel Decision"),
    ("hr.staff.reward_disciplinary.view", "HR Staff: View Reward / Disciplinary"),
    ("hr.staff.reward_disciplinary.manage", "HR Staff: Manage Reward / Disciplinary"),
)


class Migration(migrations.Migration):

    dependencies = [
        ("hr_staff", "0013_mysql_conditional_unique_backstops"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrPersonnelDecision",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True)),
                ("decision_no", models.CharField(max_length=64)),
                ("decision_type", models.CharField(choices=[("APPOINTMENT", "Appointment"), ("TRANSFER", "Transfer"), ("PROMOTION", "Promotion"), ("DEMOTION", "Demotion"), ("STATUS", "Status"), ("REWARD", "Reward"), ("DISCIPLINE", "Discipline"), ("OTHER", "Other")], max_length=24)),
                ("decision_action", models.CharField(choices=[("ISSUE", "Issue"), ("CORRECT", "Correct"), ("REVOKE", "Revoke")], default="ISSUE", max_length=16)),
                ("title", models.CharField(max_length=200)),
                ("basis_text", models.TextField(blank=True, default="")),
                ("content_snapshot_json", models.JSONField(default=dict)),
                ("decided_at", models.DateTimeField()),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("supersedes_decision_id", models.UUIDField(blank=True, null=True)),
                ("source_business_type", models.CharField(blank=True, default="", max_length=64)),
                ("source_business_id", models.CharField(blank=True, default="", max_length=64)),
                ("correlation_id", models.CharField(blank=True, default="", max_length=64)),
                ("created_by", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="personnel_decisions", to="hr_staff.hrstaffmaster")),
            ],
            options={
                "verbose_name": "HR Personnel Decision",
                "verbose_name_plural": "HR Personnel Decisions",
                "indexes": [models.Index(fields=["tenant_id", "staff", "effective_from"], name="idx_hr03_dec_staff_eff"), models.Index(fields=["tenant_id", "source_business_type", "source_business_id"], name="idx_hr03_dec_source")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "decision_no"), name="uq_hr03_dec_tenant_no"), models.UniqueConstraint(fields=("tenant_id", "supersedes_decision_id"), name="uq_hr03_dec_supersede"), models.CheckConstraint(condition=models.Q(effective_to__isnull=True) | models.Q(effective_to__gt=models.F("effective_from")), name="ck_hr03_dec_date_range")],
            },
        ),
        migrations.CreateModel(
            name="HrRewardDisciplinaryCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True)),
                ("case_no", models.CharField(max_length=64)),
                ("kind", models.CharField(choices=[("REWARD", "Reward"), ("DISCIPLINE", "Discipline")], max_length=16)),
                ("category_code", models.CharField(max_length=64)),
                ("level_code", models.CharField(blank=True, default="", max_length=64)),
                ("title", models.CharField(max_length=200)),
                ("reason_text", models.TextField(blank=True, default="")),
                ("occurred_on", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("RETURNED", "Returned"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("EFFECTIVE", "Effective"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=16)),
                ("final_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("source_business_type", models.CharField(blank=True, default="", max_length=64)),
                ("source_business_id", models.CharField(blank=True, default="", max_length=64)),
                ("correlation_id", models.CharField(blank=True, default="", max_length=64)),
                ("created_by", models.BigIntegerField(blank=True, null=True)),
                ("updated_by", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("decision", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reward_disciplinary_cases", to="hr_staff.hrpersonneldecision")),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reward_disciplinary_cases", to="hr_staff.hrstaffmaster")),
            ],
            options={
                "verbose_name": "HR Reward / Disciplinary Case",
                "verbose_name_plural": "HR Reward / Disciplinary Cases",
                "indexes": [models.Index(fields=["tenant_id", "staff", "status"], name="idx_hr03_rdc_staff_status")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr03_rdc_tenant_no"), models.CheckConstraint(condition=~models.Q(status="EFFECTIVE") | models.Q(decision__isnull=False), name="ck_hr03_rdc_eff_dec")],
            },
        ),
        migrations.AlterModelOptions(
            name="hrstaffpermissionmeta",
            options={"managed": False, "permissions": NEW_PERMISSIONS},
        ),
    ]
