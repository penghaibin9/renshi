"""Seal HR03 formal personnel decisions and install MySQL backstops."""

import hashlib
import json

from django.db import migrations, models
from django.db.models import Q


HASH_FIELDS = (
    "tenant_id",
    "decision_no",
    "staff_id",
    "decision_type",
    "decision_action",
    "title",
    "basis_text",
    "content_snapshot_json",
    "decided_at",
    "effective_from",
    "effective_to",
    "supersedes_decision_id",
    "correction_reason",
    "correction_evidence_ref",
    "source_business_type",
    "source_business_id",
    "correlation_id",
    "created_by",
    "sealed_at",
)


def _canonical(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def seal_legacy_decisions(apps, schema_editor):
    Decision = apps.get_model("hr_staff", "HrPersonnelDecision")
    batch = []
    for row in Decision.objects.all().iterator(chunk_size=500):
        # Existing correction rows predate explicit evidence references. Preserve
        # their append-only lineage while marking the migration provenance.
        if row.decision_action in {"CORRECT", "REVOKE"}:
            row.correction_reason = row.basis_text or "legacy correction"
            row.correction_evidence_ref = (
                f"legacy:hr03:personnel-decision:{row.id}"
            )
        else:
            row.correction_reason = ""
            row.correction_evidence_ref = ""
        row.sealed_at = row.created_at
        payload = {
            field: _canonical(getattr(row, field)) for field in HASH_FIELDS
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        row.content_hash = hashlib.sha256(encoded).hexdigest()
        batch.append(row)
        if len(batch) >= 500:
            Decision.objects.bulk_update(
                batch,
                [
                    "correction_reason",
                    "correction_evidence_ref",
                    "sealed_at",
                    "content_hash",
                ],
            )
            batch = []
    if batch:
        Decision.objects.bulk_update(
            batch,
            [
                "correction_reason",
                "correction_evidence_ref",
                "sealed_at",
                "content_hash",
            ],
        )


def install_mysql_personnel_decision_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    names = (
        "hr03_personnel_decision_seal_insert",
        "hr03_personnel_decision_no_update",
        "hr03_personnel_decision_no_delete",
    )
    for name in names:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")
    schema_editor.execute(
        """
        CREATE TRIGGER hr03_personnel_decision_seal_insert
        BEFORE INSERT ON hr_staff_hrpersonneldecision
        FOR EACH ROW
        BEGIN
            IF NEW.sealed_at IS NULL
               OR NEW.content_hash NOT REGEXP '^[0-9a-f]{64}$' THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR03_PERSONNEL_DECISION_SEAL_REQUIRED';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM hr_staff_hrstaffmaster staff
                WHERE staff.id = NEW.staff_id
                  AND staff.tenant_id = NEW.tenant_id
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR03_PERSONNEL_DECISION_STAFF_TENANT_MISMATCH';
            END IF;
            IF NEW.decision_action = 'ISSUE' AND (
                NEW.supersedes_decision_id IS NOT NULL
                OR NEW.correction_reason <> ''
                OR NEW.correction_evidence_ref <> ''
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR03_PERSONNEL_DECISION_LINEAGE_INVALID';
            END IF;
            IF NEW.decision_action IN ('CORRECT', 'REVOKE') AND (
                NEW.supersedes_decision_id IS NULL
                OR NEW.correction_reason = ''
                OR NEW.correction_evidence_ref = ''
                OR NOT EXISTS (
                    SELECT 1 FROM hr_staff_hrpersonneldecision parent
                    WHERE parent.id = NEW.supersedes_decision_id
                      AND parent.tenant_id = NEW.tenant_id
                      AND parent.staff_id = NEW.staff_id
                      AND parent.decision_type = NEW.decision_type
                )
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR03_PERSONNEL_DECISION_PARENT_INVALID';
            END IF;
        END
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr03_personnel_decision_no_update
        BEFORE UPDATE ON hr_staff_hrpersonneldecision
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR03_PERSONNEL_DECISION_IMMUTABLE: append a successor'
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr03_personnel_decision_no_delete
        BEFORE DELETE ON hr_staff_hrpersonneldecision
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR03_PERSONNEL_DECISION_IMMUTABLE: delete forbidden'
        """
    )


def remove_mysql_personnel_decision_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for name in (
        "hr03_personnel_decision_seal_insert",
        "hr03_personnel_decision_no_update",
        "hr03_personnel_decision_no_delete",
    ):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")


PERMISSIONS = (
    ("hr.staff.view", "HR Staff: View"),
    ("hr.staff.view_sensitive", "HR Staff: View Sensitive"),
    ("hr.staff.reveal_high_sensitive", "HR Staff: Reveal High Sensitive"),
    ("hr.staff.create", "HR Staff: Create"),
    ("hr.staff.edit_basic", "HR Staff: Edit Basic"),
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
    # CREATE/DROP TRIGGER cannot run inside an atomic migration on MySQL.
    atomic = False

    dependencies = [("hr_staff", "0014_personnel_decision_reward_disciplinary")]

    operations = [
        migrations.AlterModelOptions(
            name="hrstaffpermissionmeta",
            options={"managed": False, "permissions": PERMISSIONS},
        ),
        migrations.AlterModelOptions(
            name="hrpersonneldecision",
            options={
                "base_manager_name": "objects",
                "verbose_name": "HR Personnel Decision",
                "verbose_name_plural": "HR Personnel Decisions",
            },
        ),
        migrations.AddField(
            model_name="hrpersonneldecision",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="hrpersonneldecision",
            name="correction_evidence_ref",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.AddField(
            model_name="hrpersonneldecision",
            name="correction_reason",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.AddField(
            model_name="hrpersonneldecision",
            name="sealed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(seal_legacy_decisions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="hrpersonneldecision",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        decision_action="ISSUE",
                        supersedes_decision_id__isnull=True,
                        correction_reason="",
                        correction_evidence_ref="",
                    )
                    | (
                        Q(decision_action__in=("CORRECT", "REVOKE"))
                        & Q(supersedes_decision_id__isnull=False)
                        & ~Q(correction_reason="")
                        & ~Q(correction_evidence_ref="")
                    )
                ),
                name="ck_hr03_dec_lineage",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrpersonneldecision",
            constraint=models.CheckConstraint(
                condition=Q(sealed_at__isnull=False) & ~Q(content_hash=""),
                name="ck_hr03_dec_sealed",
            ),
        ),
        migrations.RunPython(
            install_mysql_personnel_decision_seals,
            remove_mysql_personnel_decision_seals,
        ),
    ]
