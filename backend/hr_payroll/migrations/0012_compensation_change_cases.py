import uuid

from django.db import migrations, models


UPDATE_TRIGGER = "trg_hr15_comp_change_terminal_no_update"
DELETE_TRIGGER = "trg_hr15_comp_change_no_delete"
TABLE = "hr15_compensation_change_case"


def install_change_ledger_triggers(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{UPDATE_TRIGGER}`")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{DELETE_TRIGGER}`")
    schema_editor.execute(
        f"""
        CREATE TRIGGER `{UPDATE_TRIGGER}`
        BEFORE UPDATE ON `{TABLE}`
        FOR EACH ROW
        BEGIN
            IF OLD.status IN ('APPROVED', 'REJECTED', 'CANCELLED') THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'COMPENSATION_CHANGE_DECISION_IMMUTABLE';
            END IF;
        END
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER `{DELETE_TRIGGER}`
        BEFORE DELETE ON `{TABLE}`
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'COMPENSATION_CHANGE_LEDGER_IMMUTABLE'
        """
    )


def remove_change_ledger_triggers(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{UPDATE_TRIGGER}`")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS `{DELETE_TRIGGER}`")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_payroll", "0011_external_settlement_basis_input")]

    operations = [
        migrations.CreateModel(
            name="CompensationChangeCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("case_no", models.CharField(max_length=64)),
                ("staff_id", models.UUIDField()),
                ("change_type", models.CharField(choices=[("POSITION_PAY_CHANGE", "岗位工资变更"), ("SALARY_STEP_CHANGE", "薪级变更"), ("POLICY_STANDARD_CHANGE", "政策性调资"), ("PERFORMANCE_ADJUSTMENT", "绩效工资调整"), ("ALLOWANCE_START", "津补贴启用"), ("ALLOWANCE_CHANGE", "津补贴变更"), ("ALLOWANCE_STOP", "津补贴停发"), ("BONUS", "一次性奖金"), ("SPECIAL_REWARD", "专项奖励"), ("ARREARS", "补发"), ("RECOVERY", "追扣"), ("CORRECTION", "更正")], max_length=32)),
                ("payroll_variable_key", models.CharField(max_length=64)),
                ("item_name", models.CharField(max_length=200)),
                ("amount_mode", models.CharField(choices=[("SET", "设置金额"), ("DELTA", "增减金额")], default="SET", max_length=16)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("currency_code", models.CharField(default="CNY", max_length=3)),
                ("proration_mode", models.CharField(choices=[("NONE", "不折算"), ("CALENDAR_DAYS", "按自然日折算")], default="NONE", max_length=24)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("review_date", models.DateField(blank=True, null=True)),
                ("reason_code", models.CharField(max_length=64)),
                ("note", models.TextField(blank=True, default="")),
                ("source_domain", models.CharField(blank=True, default="", max_length=16)),
                ("source_ref", models.CharField(blank=True, default="", max_length=128)),
                ("source_version", models.CharField(blank=True, default="", max_length=64)),
                ("source_snapshot_json", models.JSONField(blank=True, default=dict)),
                ("evidence_refs_json", models.JSONField(blank=True, default=list)),
                ("supersedes_case_id", models.UUIDField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "草稿"), ("SUBMITTED", "待审批"), ("APPROVED", "已批准"), ("REJECTED", "已拒绝"), ("CANCELLED", "已取消")], db_index=True, default="DRAFT", max_length=16)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("submitted_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("decided_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "hr15_compensation_change_case",
                "permissions": (("hr.payroll.change.view", "HR15: View compensation changes"), ("hr.payroll.change.manage", "HR15: Manage compensation changes"), ("hr.payroll.change.approve", "HR15: Approve compensation changes")),
                "indexes": [models.Index(fields=["tenant_id", "staff_id", "status", "effective_from"], name="idx_hr15_change_staff"), models.Index(fields=["tenant_id", "payroll_variable_key", "effective_from"], name="idx_hr15_change_variable")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr15_change_case_no"), models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gte", models.F("effective_from")), _connector="OR"), name="ck_hr15_change_effective_range")],
            },
        ),
        migrations.RunPython(
            install_change_ledger_triggers,
            reverse_code=remove_change_ledger_triggers,
        ),
    ]
