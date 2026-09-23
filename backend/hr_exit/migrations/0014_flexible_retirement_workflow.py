import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0013_evidence_access_audit")]
    operations = [
        migrations.CreateModel(name="RetirementFlexApplication", fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('updated_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('staff_id', models.UUIDField()),
                ('person_id', models.UUIDField()),
                ('employment_relationship_id', models.UUIDField()),
                ('precheck_id', models.UUIDField()),
                ('parent_application_id', models.UUIDField(blank=True, null=True)),
                ('mode', models.CharField(choices=[('EARLY','弹性提前退休'),('DELAY','弹性延迟退休'),('END_DELAY','协商终止弹性延迟')], max_length=16)),
                ('requested_date', models.DateField()),
                ('status', models.CharField(choices=[('DRAFT','草稿'),('SUBMITTED','待核验审批'),('RETURNED','退回补件'),('APPROVED','已批准，尚非退休事实'),('REJECTED','已驳回'),('CANCELLED','已撤回')], db_index=True, default='DRAFT', max_length=16)),
                ('version', models.PositiveIntegerField(default=1)),
                ('idempotency_key', models.CharField(max_length=128)),
                ('request_hash', models.CharField(max_length=64)),
                ('notice_date', models.DateField(blank=True, null=True)),
                ('notice_material_version_id', models.UUIDField(blank=True, null=True)),
                ('reason', models.CharField(max_length=1000)),
                ('authority_snapshot', models.JSONField(default=dict)),
                ('review_snapshot', models.JSONField(default=dict)),
                ('approved_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('approval_hash', models.CharField(blank=True, default='', max_length=64)),
                ('exit_case_id', models.UUIDField(blank=True, null=True)),
            ], options={
                "db_table": "hr16_retirement_flex_application",
                "permissions": [("hr.exit.flex.review", "核验与审批 HR16 弹性退休申请")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "staff_id", "idempotency_key"), name="uq_hr16_flex_self_command")],
                "indexes": [
                    models.Index(fields=("tenant_id", "employment_relationship_id", "status"), name="idx_hr16_flex_rel_status"),
                    models.Index(fields=("tenant_id", "staff_id", "created_at"), name="idx_hr16_flex_self_time"),
                    models.Index(fields=("tenant_id", "exit_case_id"), name="idx_hr16_flex_exit_case"),
                ],
            }),
        migrations.CreateModel(name="RetirementFlexEvent", fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('updated_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('application_id', models.UUIDField()),
                ('version', models.PositiveIntegerField()),
                ('action', models.CharField(max_length=32)),
                ('payload', models.JSONField(default=dict)),
                ('content_hash', models.CharField(max_length=64)),
            ], options={
                "db_table": "hr16_retirement_flex_event", "base_manager_name": "objects",
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "application_id", "version"), name="uq_hr16_flex_event_version")],
            }),
    ]
