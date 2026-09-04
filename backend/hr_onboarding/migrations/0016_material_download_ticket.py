import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_onboarding", "0015_hronboardingidempotencyrecord_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrOnboardingMaterialDownloadTicket",
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
                ("tenant_id", models.BigIntegerField(db_index=True)),
                ("file_version_id", models.UUIDField()),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("actor_user_id", models.PositiveBigIntegerField(db_index=True)),
                ("purpose", models.CharField(max_length=500)),
                ("request_id", models.CharField(blank=True, default="", max_length=64)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "material",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="download_tickets",
                        to="hr_onboarding.hronboardingmaterial",
                    ),
                ),
            ],
            options={
                "db_table": "hr05_material_download_ticket",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "material", "created_at"],
                        name="idx_hr05_mat_ticket_subject",
                    ),
                    models.Index(
                        fields=["tenant_id", "actor_user_id", "expires_at"],
                        name="idx_hr05_mat_ticket_actor",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(purpose__gt=""),
                        name="ck_hr05_mat_ticket_purpose",
                    )
                ],
            },
        )
    ]
