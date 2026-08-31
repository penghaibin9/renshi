# HR10-S10: Legacy 迁移模型
from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies = [("horilla_auth", "__first__"), ("hr10_development", "0009_integration")]
    operations = [
        migrations.CreateModel("HrDevelopmentStagingRow", [
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ("tenant_id", models.BigIntegerField(db_index=True)), ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("source_system", models.CharField(default="LEGACY_EMPLOYEE", max_length=64)), ("source_table", models.CharField(max_length=64)), ("source_field", models.CharField(blank=True, default="", max_length=64)), ("source_object_id", models.CharField(max_length=64)), ("raw_text", models.TextField(blank=True, default="")), ("parsed_data", models.JSONField(blank=True, default=dict)), ("migration_trust_level", models.CharField(default="UNKNOWN", max_length=32)), ("target_model", models.CharField(blank=True, default="", max_length=64)), ("target_id", models.BigIntegerField(blank=True, null=True)), ("verification_status", models.CharField(default="PENDING", max_length=16)), ("error_message", models.TextField(blank=True, default="")), ("import_job_id", models.BigIntegerField(blank=True, db_index=True, null=True)),
        ], options={"verbose_name": "旧数据暂存行", "verbose_name_plural": "旧数据暂存行", "db_table": "hr_development_staging_row"}),
        migrations.CreateModel("HrDevelopmentImportJob", [
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ("tenant_id", models.BigIntegerField(db_index=True)), ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("job_type", models.CharField(max_length=64)), ("file_name", models.CharField(blank=True, default="", max_length=256)), ("file_hash", models.CharField(blank=True, default="", max_length=128)), ("template_version", models.CharField(blank=True, default="", max_length=32)), ("status", models.CharField(db_index=True, default="PENDING", max_length=16)), ("total_rows", models.IntegerField(default=0)), ("processed_rows", models.IntegerField(default=0)), ("error_rows", models.IntegerField(default=0)), ("warning_rows", models.IntegerField(default=0)), ("result_summary_json", models.JSONField(blank=True, default=dict)), ("error_workbook_path", models.CharField(blank=True, default="", max_length=512)), ("retry_count", models.IntegerField(default=0)), ("started_at", models.DateTimeField(blank=True, null=True)), ("completed_at", models.DateTimeField(blank=True, null=True)),
        ], options={"verbose_name": "发展导入任务", "verbose_name_plural": "发展导入任务", "db_table": "hr_development_import_job"}),
    ]
