import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("hr_integration", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="SsoLoginEvidence",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("protocol", models.CharField(max_length=16)),
                ("status", models.CharField(choices=[("SUCCESS","登录成功"),("FAILED","登录失败")], db_index=True, max_length=16)),
                ("failure_code", models.CharField(blank=True, default="", max_length=64)),
                ("subject_fingerprint", models.CharField(blank=True, default="", max_length=64)),
                ("staff_no", models.CharField(blank=True, default="", max_length=64)),
                ("auth_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("correlation_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ("detail_json", models.JSONField(blank=True, default=dict)),
                ("happened_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sso_login_evidence", to="hr_integration.integrationconnection")),
            ],
            options={"db_table":"hrint_sso_login_evidence"},
        ),
        migrations.AddIndex(model_name="ssologinevidence", index=models.Index(fields=["tenant_id","connection","happened_at"], name="idx_hrint_sso_evidence")),
    ]
