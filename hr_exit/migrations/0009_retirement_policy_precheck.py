import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0008_exit_effect_participant_coverage")]

    operations = [
        migrations.AlterModelOptions(
            name="exitcase",
            options={
                "permissions": [
                    ("hr.exit.view", "查看 HR16 退休与离校工作区"),
                    ("hr.exit.manage", "办理 HR16 退休与离校流程"),
                    ("hr.exit.handover", "维护 HR16 离校交接清单"),
                    ("hr.exit.effect", "执行 HR16 正式离校就业关系生效"),
                    ("hr.exit.retirement_policy.manage", "维护 HR16 版本化退休政策"),
                    ("hr.exit.retirement_precheck.execute", "执行 HR16 退休日期预审"),
                ]
            },
        ),
        migrations.CreateModel(
            name="RetirementPolicy",
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
                ("retirement_type", models.CharField(max_length=32)),
                (
                    "gender_code",
                    models.CharField(
                        choices=[
                            ("ANY", "Any"),
                            ("M", "Male"),
                            ("F", "Female"),
                            ("O", "Other"),
                            ("U", "Unspecified"),
                        ],
                        default="ANY",
                        max_length=3,
                    ),
                ),
                ("staff_category_code", models.CharField(blank=True, default="", max_length=32)),
                ("relationship_type", models.CharField(blank=True, default="", max_length=32)),
                ("special_condition_code", models.CharField(blank=True, default="", max_length=64)),
                ("retirement_age_months", models.PositiveIntegerField()),
                ("minimum_service_months", models.PositiveIntegerField(default=0)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("priority", models.IntegerField(default=0)),
                ("rationale", models.TextField()),
                ("supersedes_policy_id", models.UUIDField(blank=True, null=True)),
            ],
            options={
                "db_table": "hr16_retirement_policy",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "status", "effective_from", "effective_to"],
                        name="idx_hr16_retire_policy_active",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "policy_code", "version_no"),
                        name="uq_hr16_retire_policy_ver",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("retirement_age_months__gt", 0)),
                        name="ck_hr16_retire_age_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("effective_to__isnull", True))
                        | models.Q(("effective_to__gt", models.F("effective_from"))),
                        name="ck_hr16_retire_policy_dates",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RetirementPrecheck",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("person_id", models.UUIDField(db_index=True)),
                ("employment_relationship_id", models.UUIDField(db_index=True)),
                ("as_of", models.DateField()),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("ELIGIBLE", "Eligible"),
                            ("NOT_YET", "Not yet eligible"),
                            ("MANUAL_REVIEW", "Manual review"),
                        ],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("retirement_type", models.CharField(blank=True, default="", max_length=32)),
                ("statutory_date", models.DateField(blank=True, null=True)),
                ("matched_policy_id", models.UUIDField(blank=True, null=True)),
                ("matched_policy_version", models.PositiveIntegerField(blank=True, null=True)),
                ("input_snapshot_json", models.JSONField(default=dict)),
                ("explanation_json", models.JSONField(default=dict)),
            ],
            options={
                "db_table": "hr16_retirement_precheck",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "person_id", "as_of"],
                        name="idx_hr16_retire_pre_person",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "idempotency_key"),
                        name="uq_hr16_retire_precheck_idem",
                    )
                ],
            },
        ),
    ]
