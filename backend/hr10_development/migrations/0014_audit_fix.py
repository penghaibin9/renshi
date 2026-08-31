# HR10-AUDIT-FIX: 补全 AttendanceFact + DurationLedger
from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies = [("hr10_development", "0013_seal")]
    operations = [
        migrations.CreateModel("HrEnterprisePracticeAttendanceFact", [
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ("tenant_id", models.BigIntegerField(db_index=True)), ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("assignment_id", models.BigIntegerField(db_index=True)), ("date", models.DateField()), ("start_at", models.DateTimeField(blank=True, null=True)), ("end_at", models.DateTimeField(blank=True, null=True)), ("duration_minutes", models.IntegerField(blank=True, null=True)),
            ("source", models.CharField(max_length=32)), ("source_ref", models.CharField(blank=True, default="", max_length=256)), ("trust_level", models.IntegerField(default=1)),
            ("verification_status", models.CharField(db_index=True, default="SELF_REPORTED", max_length=48)), ("anomaly_flags_json", models.JSONField(blank=True, default=dict)),
            ("verified_by", models.BigIntegerField(blank=True, null=True)), ("verified_at", models.DateTimeField(blank=True, null=True)),
        ], options={"verbose_name": "企业实践出勤事实", "verbose_name_plural": "企业实践出勤事实", "db_table": "hr_practice_attendance_fact", "unique_together": {("assignment_id", "date", "source")}}),
        migrations.CreateModel("HrDurationLedger", [
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
            ("tenant_id", models.BigIntegerField(db_index=True)), ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("assignment_id", models.BigIntegerField(db_index=True)), ("source_type", models.CharField(max_length=32)), ("source_id", models.BigIntegerField()),
            ("raw_hours", models.DecimalField(decimal_places=2, max_digits=8)), ("raw_days", models.DecimalField(decimal_places=1, default=0, max_digits=6)),
            ("eligible_hours", models.DecimalField(decimal_places=2, default=0, max_digits=8)), ("eligible_days", models.DecimalField(decimal_places=1, default=0, max_digits=6)),
            ("conversion_rule_version", models.CharField(blank=True, default="", max_length=64)), ("excluded_reason", models.CharField(blank=True, default="", max_length=64)),
            ("calculated_at", models.DateTimeField()),
        ], options={"verbose_name": "时长台账", "verbose_name_plural": "时长台账", "db_table": "hr_duration_ledger", "unique_together": {("assignment_id", "source_type", "source_id")}}),
    ]
