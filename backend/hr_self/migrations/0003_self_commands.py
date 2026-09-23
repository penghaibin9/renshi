import uuid
from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [("hr_self", "0002_self_view_permission"), ("hr_staff", "0020_self_submissions"), ("hr_exit", "0015_flexible_retirement_seals")]
    operations = [migrations.CreateModel(name="SelfCommandReceipt", fields=[
        ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
        ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
        ("created_by", models.PositiveBigIntegerField(null=True, blank=True)), ("updated_by", models.PositiveBigIntegerField(null=True, blank=True)),
        ("staff_id", models.UUIDField()), ("operation", models.CharField(max_length=32)),
        ("idempotency_key", models.CharField(max_length=128)), ("request_hash", models.CharField(max_length=64)),
        ("result", models.JSONField(default=dict)),
    ], options={"db_table": "hr17_self_command_receipt", "permissions": [("hr.self.apply", "提交本人的人事申请和材料")], "constraints": [models.UniqueConstraint(fields=("tenant_id", "staff_id", "operation", "idempotency_key"), name="uq_hr17_self_command_key")]})]
