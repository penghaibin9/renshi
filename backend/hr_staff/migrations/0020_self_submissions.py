import uuid
import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("hr_staff", "0019_material_ticket_constraints")]
    operations = [
        migrations.AddField(model_name="hrcorrectioncase", name="source_channel", field=models.CharField(max_length=16, default="HR")),
        migrations.AddField(model_name="hrcorrectioncase", name="source_snapshot_hash", field=models.CharField(max_length=64, blank=True, default="")),
        migrations.AddField(model_name="hrcorrectioncase", name="source_evidence_version_id", field=models.UUIDField(null=True, blank=True)),
        migrations.CreateModel(name="HrMaterialSubmission", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("tenant_id", models.BigIntegerField(db_index=True)),
            ("revision", models.PositiveIntegerField()),
            ("status", models.CharField(max_length=16, default="SUBMITTED")),
            ("submitted_by", models.BigIntegerField()),
            ("evidence_hash", models.CharField(max_length=64)),
            ("review_reason", models.CharField(max_length=512, blank=True, default="")),
            ("reviewed_by", models.BigIntegerField(null=True, blank=True)),
            ("reviewed_at", models.DateTimeField(null=True, blank=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("request", models.ForeignKey(to="hr_staff.hrmaterialrequest", on_delete=django.db.models.deletion.PROTECT, related_name="submissions")),
            ("material_version", models.ForeignKey(to="hr_staff.hrstaffmaterialversion", on_delete=django.db.models.deletion.PROTECT, related_name="self_submissions")),
        ], options={"db_table": "hr03_material_submission", "constraints": [models.UniqueConstraint(fields=("tenant_id", "request", "revision"), name="uq_hr03_material_response_rev")], "indexes": [models.Index(fields=("tenant_id", "status", "created_at"), name="idx_hr03_material_review")]}),
    ]
