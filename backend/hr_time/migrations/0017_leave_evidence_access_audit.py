import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_time", "0016_leave_evidence_private_file"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HrLeaveEvidenceAccessAudit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("tenant_id", models.BigIntegerField(db_index=True, verbose_name="Tenant ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("purpose", models.CharField(max_length=500)),
                ("request_id", models.CharField(blank=True, default="", max_length=128)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "evidence",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_audits",
                        to="hr_time.hrleaveevidence",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "hr11_leave_evidence_access_audit",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "evidence", "created_at"],
                        name="idx_hr11_leave_evid_access",
                    ),
                    models.Index(
                        fields=["tenant_id", "actor_user_id", "created_at"],
                        name="idx_hr11_leave_actor_access",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(purpose__gt=""),
                        name="ck_hr11_leave_access_purpose",
                    )
                ],
            },
        )
    ]
