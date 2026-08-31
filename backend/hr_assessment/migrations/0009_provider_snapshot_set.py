import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("hr_assessment", "0008_calibration_revision_uuid_default")]

    operations = [
        migrations.CreateModel(
            name="HrProviderSnapshotSet",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True, help_text="学校租户标识 — fail-closed；不可为 NULL", verbose_name="租户 ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("case_id", models.UUIDField(db_index=True, verbose_name="考核 Case ID")),
                ("as_of", models.DateTimeField(verbose_name="证据 as-of 时间")),
                ("required_providers_json", models.JSONField(default=list, verbose_name="必需 Provider")),
                ("provider_status_json", models.JSONField(default=dict, verbose_name="Provider 状态")),
                ("content_hash", models.CharField(max_length=64, verbose_name="快照集哈希")),
                ("status", models.CharField(db_index=True, default="BLOCKED", max_length=30, verbose_name="状态")),
                ("captured_at", models.DateTimeField(null=True, verbose_name="采集完成时间")),
                ("request_id", models.CharField(blank=True, default="", max_length=100, verbose_name="请求追踪 ID")),
            ],
            options={
                "verbose_name": "Provider 证据快照集",
                "db_table": "hr_assessment_provider_snapshot_set",
                "indexes": [models.Index(fields=["tenant_id", "case_id", "status"], name="hr12_pss_case_status_idx")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "case_id", "content_hash"), name="uniq_hr12_provider_snapshot_hash")],
            },
        ),
        migrations.CreateModel(
            name="HrProviderSnapshotItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.BigIntegerField(db_index=True, help_text="学校租户标识 — fail-closed；不可为 NULL", verbose_name="租户 ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("case_id", models.UUIDField(db_index=True, verbose_name="考核 Case ID")),
                ("provider_type", models.CharField(max_length=50, verbose_name="Provider 类型")),
                ("source_object_type", models.CharField(max_length=100, verbose_name="源对象类型")),
                ("source_object_id", models.CharField(max_length=100, verbose_name="源对象 ID")),
                ("source_version", models.CharField(default="", max_length=50, verbose_name="源版本")),
                ("source_as_of", models.DateTimeField(null=True, verbose_name="源数据 as-of 时间")),
                ("trust_level", models.CharField(default="SOURCE_VERIFIED", max_length=30, verbose_name="可信度")),
                ("snapshot_hash", models.CharField(max_length=64, verbose_name="证据哈希")),
                ("snapshot_json", models.JSONField(default=dict, verbose_name="证据快照")),
                ("status", models.CharField(db_index=True, max_length=30, verbose_name="证据状态")),
                ("error_message", models.TextField(blank=True, default="", verbose_name="错误信息")),
                ("snapshot_set", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="hr_assessment.hrprovidersnapshotset", verbose_name="Provider 快照集")),
            ],
            options={
                "verbose_name": "Provider 证据快照条目",
                "db_table": "hr_assessment_provider_snapshot_item",
                "indexes": [models.Index(fields=["tenant_id", "case_id", "provider_type"], name="hr12_psi_case_provider_idx")],
                "constraints": [models.UniqueConstraint(fields=("tenant_id", "snapshot_set", "provider_type", "source_object_type", "source_object_id"), name="uniq_hr12_provider_snapshot_item")],
            },
        ),
    ]
