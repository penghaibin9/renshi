import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_assessment", "0026_reseal_published_authority_versions"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrAssessmentDocumentAccessAudit",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "tenant_id",
                    models.BigIntegerField(
                        db_index=True,
                        help_text="学校租户标识 — fail-closed；不可为 NULL",
                        verbose_name="租户 ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("purpose", models.CharField(max_length=500)),
                ("request_id", models.CharField(blank=True, default="", max_length=128)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_audits",
                        to="hr_assessment.hrassessmentdocument",
                    ),
                ),
            ],
            options={
                "db_table": "hr12_document_access_audit",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "document", "created_at"],
                        name="idx_hr12_doc_access",
                    ),
                    models.Index(
                        fields=["tenant_id", "actor_user_id", "created_at"],
                        name="idx_hr12_doc_actor_access",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(purpose__gt=""),
                        name="ck_hr12_doc_access_purpose",
                    )
                ],
            },
        )
    ]
