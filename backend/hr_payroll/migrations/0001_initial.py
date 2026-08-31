import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PayrollProfile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("staff_id", models.UUIDField()),
                ("payroll_identity_no", models.CharField(max_length=64)),
                ("pay_group_code", models.CharField(max_length=64)),
                ("currency_code", models.CharField(default="CNY", max_length=3)),
                ("payment_account_ref", models.CharField(blank=True, default="", max_length=128)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("ENDED", "Ended")], db_index=True, default="ACTIVE", max_length=16)),
            ],
            options={"db_table": "hr15_payroll_profile"},
        ),
        migrations.CreateModel(
            name="PayrollPeriod",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("period_code", models.CharField(max_length=32)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("INPUT_FROZEN", "Input frozen"), ("CALCULATED", "Calculated"), ("REVIEWED", "Reviewed"), ("FINALIZED", "Finalized"), ("CLOSED", "Closed")], db_index=True, default="OPEN", max_length=24)),
                ("finalized_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr15_payroll_period"},
        ),
        migrations.CreateModel(
            name="PayrollResultFact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("result_no", models.CharField(max_length=64)),
                ("payroll_period_id", models.UUIDField()),
                ("staff_id", models.UUIDField()),
                ("currency_code", models.CharField(default="CNY", max_length=3)),
                ("gross_amount", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("deduction_amount", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("net_amount", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("FINALIZED", "Finalized"), ("ADJUSTED", "Adjusted"), ("REVERSED", "Reversed")], db_index=True, default="DRAFT", max_length=16)),
                ("supersedes_result_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr15_payroll_result_fact"},
        ),
        migrations.AddConstraint(
            model_name="payrollprofile",
            constraint=models.UniqueConstraint(fields=("tenant_id", "payroll_identity_no"), name="uq_hr15_profile_tenant_identity"),
        ),
        migrations.AddConstraint(
            model_name="payrollprofile",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", models.F("effective_from")), _connector="OR"), name="ck_hr15_profile_effective_range"),
        ),
        migrations.AddIndex(
            model_name="payrollprofile",
            index=models.Index(fields=["tenant_id", "staff_id", "status"], name="idx_hr15_profile_tenant_staff"),
        ),
        migrations.AddConstraint(
            model_name="payrollperiod",
            constraint=models.UniqueConstraint(fields=("tenant_id", "period_code"), name="uq_hr15_period_tenant_code"),
        ),
        migrations.AddConstraint(
            model_name="payrollperiod",
            constraint=models.CheckConstraint(condition=models.Q(("end_date__gt", models.F("start_date"))), name="ck_hr15_period_date_range"),
        ),
        migrations.AddIndex(
            model_name="payrollperiod",
            index=models.Index(fields=["tenant_id", "status", "start_date"], name="idx_hr15_period_tenant_status"),
        ),
        migrations.AddConstraint(
            model_name="payrollresultfact",
            constraint=models.UniqueConstraint(fields=("tenant_id", "result_no"), name="uq_hr15_result_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="payrollresultfact",
            index=models.Index(fields=["tenant_id", "payroll_period_id", "staff_id"], name="idx_hr15_result_period_staff"),
        ),
        migrations.AddIndex(
            model_name="payrollresultfact",
            index=models.Index(fields=["tenant_id", "staff_id", "status"], name="idx_hr15_result_tenant_staff"),
        ),
    ]
