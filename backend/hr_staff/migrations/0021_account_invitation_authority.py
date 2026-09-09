"""Account invitation authority and explicit account-management permission."""

import uuid

import django.db.models.deletion
from django.db import migrations, models


HR_STAFF_PERMISSIONS = (
    ("hr.staff.view", "HR Staff: View"),
    ("hr.staff.view_sensitive", "HR Staff: View Sensitive"),
    ("hr.staff.reveal_high_sensitive", "HR Staff: Reveal High Sensitive"),
    ("hr.staff.create", "HR Staff: Create"),
    ("hr.staff.edit_basic", "HR Staff: Edit Basic"),
    ("hr.staff.account.manage", "HR Staff: Manage Account Invitations"),
    ("hr.staff.export", "HR Staff: Export"),
    ("hr.staff.export_sensitive", "HR Staff: Export Sensitive"),
    ("hr.staff.import", "HR Staff: Import"),
    ("hr.staff.assignment.view", "HR Staff: View Assignment"),
    ("hr.staff.assignment.correct", "HR Staff: Correct Assignment"),
    ("hr.staff.background.view", "HR Staff: View Background"),
    ("hr.staff.background.manage", "HR Staff: Manage Background"),
    ("hr.staff.material.view", "HR Staff: View Material"),
    ("hr.staff.material.upload", "HR Staff: Upload Material"),
    ("hr.staff.material.verify", "HR Staff: Verify Material"),
    ("hr.staff.material.download_sensitive", "HR Staff: Download Sensitive Material"),
    ("hr.staff.correction.view", "HR Staff: View Correction"),
    ("hr.staff.correction.create", "HR Staff: Create Correction"),
    ("hr.staff.correction.review", "HR Staff: Review Correction"),
    ("hr.staff.correction.approve_high_risk", "HR Staff: Approve High Risk Correction"),
    ("hr.staff.audit.view", "HR Staff: View Audit"),
    ("hr.staff.data_quality.manage", "HR Staff: Manage Data Quality"),
    ("hr.staff.personnel_decision.view", "HR Staff: View Personnel Decision"),
    ("hr.staff.personnel_decision.manage", "HR Staff: Manage Personnel Decision"),
    ("hr.staff.personnel_decision.correct", "HR Staff: Correct Personnel Decision"),
    ("hr.staff.personnel_decision.revoke", "HR Staff: Revoke Personnel Decision"),
    ("hr.staff.reward_disciplinary.view", "HR Staff: View Reward / Disciplinary"),
    ("hr.staff.reward_disciplinary.manage", "HR Staff: Manage Reward / Disciplinary"),
)


class Migration(migrations.Migration):
    dependencies = [
        ("hr_staff", "0020_account_link_lookup_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="HrAccountInvitation",
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
                ("invited_email", models.EmailField(max_length=254)),
                ("token_digest", models.CharField(max_length=71, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by_user_id", models.BigIntegerField(blank=True, null=True)),
                ("accepted_user_id", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "staff_id",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="account_invitations",
                        to="hr_staff.hrstaffmaster",
                    ),
                ),
            ],
            options={
                "verbose_name": "HR Account Invitation",
                "verbose_name_plural": "HR Account Invitations",
                "indexes": [
                    models.Index(
                        fields=[
                            "tenant_id",
                            "staff_id",
                            "accepted_at",
                            "revoked_at",
                        ],
                        name="hr_invite_staff_state",
                    ),
                    models.Index(
                        fields=["tenant_id", "expires_at"],
                        name="hr_invite_tenant_exp",
                    ),
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="hrstaffpermissionmeta",
            options={"managed": False, "permissions": HR_STAFF_PERMISSIONS},
        ),
    ]
