# HR10-S2: 发展计划模型
# Generated migration

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("horilla_auth", "__first__"),
        ("hr10_development", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrDevelopmentPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(db_index=True, verbose_name="Tenant ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("plan_no", models.CharField(max_length=64, verbose_name="计划编号")),
                ("plan_type", models.CharField(choices=[("SCHOOL", "校级计划"), ("COLLEGE", "院级计划"), ("TEAM", "团队计划"), ("INDIVIDUAL", "个人计划")], db_index=True, max_length=32, verbose_name="计划类型")),
                ("owner_org_id", models.BigIntegerField(blank=True, help_text="引用 HR02 Organization", null=True, verbose_name="归属组织 ID")),
                ("staff_master_id", models.BigIntegerField(blank=True, db_index=True, help_text="引用 HR03 HrStaffMaster；plan_type=INDIVIDUAL 时必填", null=True, verbose_name="个人计划所属教职工 ID")),
                ("cycle_type", models.CharField(choices=[("ANNUAL", "年度"), ("MULTI_YEAR", "多年期"), ("CUSTOM", "自定义")], default="ANNUAL", max_length=32, verbose_name="周期类型")),
                ("start_date", models.DateField(verbose_name="开始日期")),
                ("end_date", models.DateField(verbose_name="结束日期")),
                ("current_version_id", models.BigIntegerField(blank=True, null=True, verbose_name="当前版本 ID")),
                ("lifecycle_status", models.CharField(choices=[("DRAFT", "草稿"), ("PREPARING", "筹备中"), ("READY_FOR_REVIEW", "待审核"), ("UNDER_REVIEW", "审核中"), ("APPROVED", "已批准"), ("PUBLISHED", "已发布"), ("ACTIVE", "执行中"), ("CLOSING", "关闭中"), ("CLOSED", "已关闭"), ("ARCHIVED", "已归档"), ("RETURNED", "退回修改"), ("REJECTED", "已否决"), ("CANCELLED", "已取消"), ("SUPERSEDED", "已被替代")], db_index=True, default="DRAFT", max_length=32, verbose_name="生命周期状态")),
                ("source_policy_version", models.CharField(blank=True, default="", max_length=64, verbose_name="来源政策版本")),
                ("approved_at", models.DateTimeField(blank=True, null=True, verbose_name="批准时间")),
                ("published_at", models.DateTimeField(blank=True, null=True, verbose_name="发布时间")),
                ("version", models.IntegerField(default=1, verbose_name="乐观锁版本")),
            ],
            options={
                "verbose_name": "教师发展计划",
                "verbose_name_plural": "教师发展计划",
                "db_table": "hr_development_plan",
                "unique_together": {("tenant_id", "plan_no")},
                "indexes": [
                    models.Index(fields=["tenant_id", "lifecycle_status"], name="hr_dev_plan_tenant_status_idx"),
                    models.Index(fields=["tenant_id", "plan_type"], name="hr_dev_plan_tenant_type_idx"),
                    models.Index(fields=["tenant_id", "owner_org_id"], name="hr_dev_plan_tenant_org_idx"),
                    models.Index(fields=["staff_master_id", "lifecycle_status"], name="hr_dev_plan_staff_status_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(check=models.Q(("start_date__lte", models.F("end_date"))), name="plan_start_before_end"),
                ],
            },
        ),
        migrations.CreateModel(
            name="HrDevelopmentPlanVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(db_index=True, verbose_name="Tenant ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("plan_id", models.BigIntegerField(db_index=True, verbose_name="计划 ID")),
                ("version_no", models.IntegerField(default=1, verbose_name="版本号")),
                ("status", models.CharField(choices=[("DRAFT", "草稿"), ("FROZEN", "已冻结")], default="DRAFT", max_length=16, verbose_name="版本状态")),
                ("objectives_json", models.JSONField(default=dict, verbose_name="目标")),
                ("population_snapshot_json", models.JSONField(default=dict, verbose_name="覆盖人群快照")),
                ("budget_snapshot_json", models.JSONField(default=dict, verbose_name="预算快照")),
                ("policy_snapshot_json", models.JSONField(default=dict, verbose_name="政策快照")),
                ("target_snapshot_json", models.JSONField(default=dict, verbose_name="目标快照")),
                ("content_hash", models.CharField(blank=True, default="", max_length=128, verbose_name="内容哈希")),
                ("effective_from", models.DateField(blank=True, null=True, verbose_name="生效日期")),
            ],
            options={
                "verbose_name": "发展计划版本",
                "verbose_name_plural": "发展计划版本",
                "db_table": "hr_development_plan_version",
                "unique_together": {("plan_id", "version_no")},
                "indexes": [
                    models.Index(fields=["plan_id", "status"], name="hr_dev_planver_plan_status_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="HrDevelopmentNeed",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(db_index=True, verbose_name="Tenant ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("plan_version_id", models.BigIntegerField(db_index=True, verbose_name="计划版本 ID")),
                ("staff_master_id", models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="教职工 ID")),
                ("organization_id", models.BigIntegerField(blank=True, null=True, verbose_name="组织 ID")),
                ("need_type", models.CharField(db_index=True, max_length=64, verbose_name="需求类型")),
                ("source_type", models.CharField(choices=[("SELF", "教师自评"), ("MANAGER", "主管建议"), ("HR", "人事建议"), ("HR12", "考核反馈"), ("ACADEMIC", "教务反馈"), ("POLICY", "政策要求"), ("SKILL_GAP", "能力缺口分析"), ("OTHER", "其他")], max_length=32, verbose_name="来源")),
                ("source_ref", models.CharField(blank=True, default="", max_length=256, verbose_name="来源引用")),
                ("competency_ref", models.CharField(blank=True, default="", max_length=128, verbose_name="能力域引用")),
                ("current_level", models.CharField(blank=True, default="", max_length=32, verbose_name="当前水平")),
                ("target_level", models.CharField(blank=True, default="", max_length=32, verbose_name="目标水平")),
                ("priority", models.IntegerField(default=3, verbose_name="优先级 1-5")),
                ("evidence_refs", models.JSONField(blank=True, default=dict, verbose_name="证据引用")),
                ("rationale", models.TextField(blank=True, default="", verbose_name="需求说明")),
                ("status", models.CharField(default="OPEN", max_length=16, verbose_name="状态")),
            ],
            options={
                "verbose_name": "发展需求",
                "verbose_name_plural": "发展需求",
                "db_table": "hr_development_need",
                "indexes": [
                    models.Index(fields=["plan_version_id", "status"], name="hr_dev_need_planver_status_idx"),
                    models.Index(fields=["staff_master_id", "status"], name="hr_dev_need_staff_status_idx"),
                    models.Index(fields=["organization_id", "priority"], name="hr_dev_need_org_prio_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="HrDevelopmentTarget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(db_index=True, verbose_name="Tenant ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("plan_version_id", models.BigIntegerField(db_index=True, verbose_name="计划版本 ID")),
                ("target_type", models.CharField(max_length=64, verbose_name="目标类型")),
                ("target_scope", models.CharField(default="ALL", max_length=32, verbose_name="目标范围")),
                ("target_value_json", models.JSONField(default=dict, verbose_name="目标值")),
                ("unit", models.CharField(choices=[("HOURS", "学时"), ("DAYS", "天数"), ("MONTHS", "月数"), ("CREDITS", "学分"), ("COUNT", "次数")], max_length=16, verbose_name="单位")),
                ("deadline", models.DateField(blank=True, null=True, verbose_name="截止日期")),
                ("required_activity_types", models.JSONField(blank=True, default=list, verbose_name="要求活动类型")),
                ("metric_definition_id", models.CharField(blank=True, default="", max_length=128, verbose_name="度量定义 ID")),
                ("mandatory", models.BooleanField(default=False, verbose_name="必修")),
                ("source_rule_ref", models.CharField(blank=True, default="", max_length=256, verbose_name="来源规则引用")),
            ],
            options={
                "verbose_name": "发展目标",
                "verbose_name_plural": "发展目标",
                "db_table": "hr_development_target",
                "indexes": [
                    models.Index(fields=["plan_version_id", "target_type"], name="hr_dev_target_planver_type_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="HrDevelopmentBudgetPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.BigIntegerField(db_index=True, verbose_name="Tenant ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("plan_version_id", models.BigIntegerField(db_index=True, verbose_name="计划版本 ID")),
                ("funding_source_id", models.CharField(blank=True, default="", max_length=64, verbose_name="经费来源 ID")),
                ("currency", models.CharField(default="CNY", max_length=8, verbose_name="币种")),
                ("planned_amount", models.DecimalField(decimal_places=2, max_digits=14, verbose_name="计划金额")),
                ("reserved_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="已预留金额")),
                ("committed_amount", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="已承诺金额")),
                ("actual_paid_projection", models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name="实际支付投影")),
                ("organization_id", models.BigIntegerField(blank=True, null=True, verbose_name="归属组织 ID")),
                ("activity_type", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="活动类型")),
                ("budget_period", models.CharField(blank=True, default="", max_length=32, verbose_name="预算期间")),
                ("external_budget_ref", models.CharField(blank=True, default="", max_length=256, verbose_name="外部预算引用")),
                ("version", models.IntegerField(default=1, verbose_name="乐观锁版本")),
            ],
            options={
                "verbose_name": "发展预算计划",
                "verbose_name_plural": "发展预算计划",
                "db_table": "hr_development_budget_plan",
                "indexes": [
                    models.Index(fields=["plan_version_id", "activity_type"], name="hr_dev_budget_planver_type_idx"),
                    models.Index(fields=["plan_version_id", "organization_id"], name="hr_dev_budget_planver_org_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(check=models.Q(("planned_amount__gte", 0)), name="budget_planned_non_negative"),
                    models.CheckConstraint(check=models.Q(("reserved_amount__gte", 0)), name="budget_reserved_non_negative"),
                    models.CheckConstraint(check=models.Q(("committed_amount__gte", 0)), name="budget_committed_non_negative"),
                ],
            },
        ),
        # FK for created_by/updated_by
        migrations.AddField(model_name="hrdevelopmentplan", name="created_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="创建人")),
        migrations.AddField(model_name="hrdevelopmentplan", name="updated_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="更新人")),
        migrations.AddField(model_name="hrdevelopmentplanversion", name="created_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="创建人")),
        migrations.AddField(model_name="hrdevelopmentplanversion", name="updated_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="更新人")),
        migrations.AddField(model_name="hrdevelopmentneed", name="created_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="创建人")),
        migrations.AddField(model_name="hrdevelopmentneed", name="updated_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="更新人")),
        migrations.AddField(model_name="hrdevelopmenttarget", name="created_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="创建人")),
        migrations.AddField(model_name="hrdevelopmenttarget", name="updated_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="更新人")),
        migrations.AddField(model_name="hrdevelopmentbudgetplan", name="created_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="创建人")),
        migrations.AddField(model_name="hrdevelopmentbudgetplan", name="updated_by", field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=models.deletion.SET_NULL, related_name="+", to="horilla_auth.horillauser", verbose_name="更新人")),
    ]
