import uuid
from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies = [("hr_data", "0016_materialize_submission_permissions")]
    operations = [migrations.CreateModel(name="OperationalSnapshot", fields=[
        ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
        ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
        ("created_by", models.PositiveBigIntegerField(null=True, blank=True)), ("updated_by", models.PositiveBigIntegerField(null=True, blank=True)),
        ("idempotency_key", models.CharField(max_length=128)), ("request_hash", models.CharField(max_length=64)),
        ("catalog_version", models.CharField(max_length=64)), ("payload", models.JSONField(default=dict)),
        ("evidence_hash", models.CharField(max_length=64)),
    ], options={"db_table": "hr18_operational_snapshot", "permissions": [("hr.data.snapshot.capture", "冻结学校全域人事运行观察快照")],
        "constraints": [models.UniqueConstraint(fields=("tenant_id", "idempotency_key"), name="uq_hr18_observation_command")],
        "indexes": [models.Index(fields=("tenant_id", "created_at"), name="idx_hr18_observation_time")]})]
