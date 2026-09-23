import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='HrIntegrationPermissionMeta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'permissions': (('hr.integration.view', '查看高校人事 Integration Hub'), ('hr.integration.manage', '维护学校接口与字段映射'), ('hr.integration.test', '执行接口连通性测试')),
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='IntegrationAuditEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('actor_user_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('event_type', models.CharField(db_index=True, max_length=64)),
                ('connection_code', models.CharField(blank=True, default='', max_length=64)),
                ('summary', models.CharField(max_length=255)),
                ('payload_json', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'db_table': 'hrint_audit_event',
                'indexes': [models.Index(fields=['tenant_id', 'created_at'], name='idx_hrint_audit_tenant')],
            },
        ),
        migrations.CreateModel(
            name='IntegrationConnection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('updated_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('code', models.CharField(max_length=64)),
                ('name', models.CharField(max_length=160)),
                ('category', models.CharField(choices=[('SSO', '统一认证'), ('MASTER_DATA', '组织人员 / 主数据'), ('RESEARCH', '科研'), ('ACADEMIC', '教务'), ('FINANCE', '财务'), ('ATTENDANCE', '考勤 / 门禁 / 一卡通'), ('ESIGN', '电子签章'), ('NOTIFICATION', '短信 / 邮件 / 企业微信')], db_index=True, max_length=24)),
                ('adapter_code', models.CharField(db_index=True, max_length=64)),
                ('base_url', models.CharField(blank=True, default='', max_length=500)),
                ('enabled', models.BooleanField(default=False)),
                ('config_json', models.JSONField(blank=True, default=dict)),
                ('secret_ciphertext', models.TextField(blank=True, default='', editable=False)),
                ('credential_updated_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('DRAFT', '待配置'), ('CONFIGURED', '已配置'), ('VERIFIED', '已验证'), ('ERROR', '验证失败')], db_index=True, default='DRAFT', max_length=16)),
                ('last_test_at', models.DateTimeField(blank=True, null=True)),
                ('last_test_status', models.CharField(blank=True, default='', max_length=32)),
                ('last_test_message', models.CharField(blank=True, default='', max_length=255)),
            ],
            options={
                'db_table': 'hrint_connection',
                'indexes': [models.Index(fields=['tenant_id', 'category', 'enabled'], name='idx_hrint_category')],
                'constraints': [models.UniqueConstraint(fields=('tenant_id', 'code'), name='uq_hrint_tenant_code')],
            },
        ),
        migrations.CreateModel(
            name='IntegrationMappingProfile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('updated_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('code', models.CharField(max_length=64)),
                ('name', models.CharField(max_length=160)),
                ('direction', models.CharField(choices=[('INBOUND', '外部 → 人事'), ('OUTBOUND', '人事 → 外部'), ('BIDIRECTIONAL', '双向')], max_length=16)),
                ('source_object', models.CharField(blank=True, default='', max_length=96)),
                ('target_domain', models.CharField(max_length=32)),
                ('enabled', models.BooleanField(default=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mapping_profiles', to='hr_integration.integrationconnection')),
            ],
            options={
                'db_table': 'hrint_mapping_profile',
            },
        ),
        migrations.CreateModel(
            name='IntegrationFieldMapping',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('updated_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('source_field', models.CharField(max_length=160)),
                ('target_field', models.CharField(max_length=160)),
                ('transform_code', models.CharField(blank=True, default='DIRECT', max_length=64)),
                ('required', models.BooleanField(default=False)),
                ('default_value', models.CharField(blank=True, default='', max_length=255)),
                ('sort_order', models.PositiveIntegerField(default=10)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fields', to='hr_integration.integrationmappingprofile')),
            ],
            options={
                'db_table': 'hrint_field_mapping',
                'ordering': ('sort_order', 'source_field'),
            },
        ),
        migrations.CreateModel(
            name='IntegrationTestRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tenant_id', models.PositiveBigIntegerField(db_index=True)),
                ('adapter_code', models.CharField(max_length=64)),
                ('status', models.CharField(max_length=32)),
                ('summary', models.CharField(max_length=255)),
                ('detail_json', models.JSONField(blank=True, default=dict)),
                ('tested_by', models.PositiveBigIntegerField(blank=True, null=True)),
                ('tested_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='test_runs', to='hr_integration.integrationconnection')),
            ],
            options={
                'db_table': 'hrint_test_run',
            },
        ),
        migrations.AddConstraint(
            model_name='integrationmappingprofile',
            constraint=models.UniqueConstraint(fields=('connection', 'code'), name='uq_hrint_mapping_code'),
        ),
        migrations.AddConstraint(
            model_name='integrationfieldmapping',
            constraint=models.UniqueConstraint(fields=('profile', 'source_field'), name='uq_hrint_source_field'),
        ),
        migrations.AddConstraint(
            model_name='integrationfieldmapping',
            constraint=models.UniqueConstraint(fields=('profile', 'sort_order'), name='uq_hrint_mapping_order'),
        ),
        migrations.AddIndex(
            model_name='integrationtestrun',
            index=models.Index(fields=['tenant_id', 'tested_at'], name='idx_hrint_test_tenant'),
        ),
    ]
