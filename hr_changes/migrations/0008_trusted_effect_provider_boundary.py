import hashlib
import json
import uuid

from django.db import migrations, models


SNAPSHOT_TABLE = "hr_changes_hrchangeeffectivesnapshot"
CASE_TABLE = "hr_changes_hrpersonnelchangecase"


def _hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def remove_execution_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for name in (
        f"{SNAPSHOT_TABLE}_seal_insert",
        f"{SNAPSHOT_TABLE}_no_update",
        f"{SNAPSHOT_TABLE}_no_delete",
        "hr06_case_no_fake_effective_insert",
        "hr06_case_trusted_effective_update",
        "hr06_approval_snapshot_frozen_update",
        "hr06_approval_snapshot_frozen_delete",
        "hr06_transition_no_update",
        "hr06_transition_no_delete",
    ):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")


def backfill_trusted_effect_fields(apps, schema_editor):
    Snapshot = apps.get_model("hr_changes", "HrChangeEffectiveSnapshot")
    alias = schema_editor.connection.alias
    for row in Snapshot.objects.using(alias).select_related("change_case_id").all().iterator(chunk_size=500):
        case = row.change_case_id
        try:
            approval_id = uuid.UUID(case.approval_instance_id) if case.approval_instance_id else None
        except (TypeError, ValueError):
            approval_id = None
        receipt = {
            "legacy": True,
            "caseId": str(case.id),
            "targetFactIds": row.target_fact_ids_json or [],
        }
        row.case_version = case.version
        row.approval_snapshot_id = approval_id
        row.approval_snapshot_hash = ""
        row.provider_code = "LEGACY_UNVERIFIED"
        row.provider_receipt_json = receipt
        row.provider_receipt_hash = _hash(receipt)
        row.execution_idempotency_key = f"legacy:{case.id}"
        payload = {
            "tenantId": int(row.tenant_id),
            "changeCaseId": str(case.id),
            "staffId": str(case.staff_master_id_id),
            "appliedAt": row.applied_at.isoformat(),
            "effectiveAt": row.effective_at.isoformat(),
            "before": row.before_json or {},
            "after": row.after_json or {},
            "sourceFactIds": row.source_fact_ids_json or [],
            "targetFactIds": row.target_fact_ids_json or [],
            "positionChanges": row.position_changes_json or {},
            "downstreamPlanVersion": int(row.downstream_plan_version),
            "legacyChecksum": row.checksum or "",
            "authorityDomain": row.authority_domain,
            "authorityContractVersion": int(row.authority_contract_version),
            "caseVersion": int(row.case_version),
            "approvalSnapshotId": str(approval_id) if approval_id else None,
            "approvalSnapshotHash": "",
            "providerCode": "LEGACY_UNVERIFIED",
            "providerReceipt": receipt,
            "providerReceiptHash": row.provider_receipt_hash,
            "executionIdempotencyKey": row.execution_idempotency_key,
        }
        row.content_hash = _hash(payload)
        row.save(
            update_fields=[
                "case_version",
                "approval_snapshot_id",
                "approval_snapshot_hash",
                "provider_code",
                "provider_receipt_json",
                "provider_receipt_hash",
                "execution_idempotency_key",
                "content_hash",
            ]
        )


def install_trusted_execution_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    remove_execution_triggers(apps, schema_editor)
    schema_editor.execute(
        f"CREATE TRIGGER {SNAPSHOT_TABLE}_no_update BEFORE UPDATE ON {SNAPSHOT_TABLE} "
        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_EVIDENCE_IMMUTABLE'"
    )
    schema_editor.execute(
        f"CREATE TRIGGER {SNAPSHOT_TABLE}_no_delete BEFORE DELETE ON {SNAPSHOT_TABLE} "
        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_EVIDENCE_IMMUTABLE'"
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER {SNAPSHOT_TABLE}_seal_insert
        BEFORE INSERT ON {SNAPSHOT_TABLE}
        FOR EACH ROW
        BEGIN
            IF NEW.sealed_at IS NULL OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR NEW.authority_domain <> 'HR03' OR NEW.authority_contract_version <> 1
               OR NEW.provider_code <> 'HR06_CANONICAL_HR02_HR03_V1'
               OR NEW.provider_receipt_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR NEW.approval_snapshot_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR NEW.approval_snapshot_id IS NULL
               OR COALESCE(NEW.execution_idempotency_key, '') = ''
               OR JSON_CONTAINS_PATH(
                    NEW.provider_receipt_json, 'all', '$.providerCode', '$.tenantId',
                    '$.caseId', '$.caseVersion', '$.staffId', '$.actionCode',
                    '$.effectiveAt', '$.approvalSnapshotId', '$.approvalSnapshotHash',
                    '$.idempotencyKey', '$.sourceFactIds', '$.targetFactIds'
                  ) = 0
               OR JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.providerCode')) <> NEW.provider_code
               OR CAST(JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.tenantId')) AS UNSIGNED) <> NEW.tenant_id
               OR REPLACE(JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.caseId')), '-', '') <> NEW.change_case_id_id
               OR CAST(JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.caseVersion')) AS UNSIGNED) <> NEW.case_version
               OR JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.effectiveAt')) <> DATE_FORMAT(NEW.effective_at, '%Y-%m-%d')
               OR REPLACE(JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.approvalSnapshotId')), '-', '') <> NEW.approval_snapshot_id
               OR JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.approvalSnapshotHash')) <> NEW.approval_snapshot_hash
               OR JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.idempotencyKey')) <> NEW.execution_idempotency_key
               OR JSON_LENGTH(JSON_EXTRACT(NEW.provider_receipt_json, '$.sourceFactIds')) = 0
               OR JSON_LENGTH(JSON_EXTRACT(NEW.provider_receipt_json, '$.targetFactIds')) = 0 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_TRUSTED_EXECUTION_RECEIPT_INVALID';
            END IF;
            IF (SELECT COUNT(*) FROM {CASE_TABLE} c
                JOIN hr_staff_hrstaffmaster s ON s.id = c.staff_master_id_id
                JOIN hr_changes_hrchangeaction a ON a.id = c.action_id_id
                WHERE c.id = NEW.change_case_id_id AND c.tenant_id = NEW.tenant_id
                  AND s.tenant_id = NEW.tenant_id AND c.status = 'APPLYING'
                  AND NEW.case_version = c.version + 1
                  AND REPLACE(JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.staffId')), '-', '') = c.staff_master_id_id
                  AND JSON_UNQUOTE(JSON_EXTRACT(NEW.provider_receipt_json, '$.actionCode')) = a.code) <> 1 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_PARENT_LINEAGE_INVALID';
            END IF;
            IF (SELECT COUNT(*) FROM hr_changes_hrchangeapprovalsnapshot a
                WHERE a.id = NEW.approval_snapshot_id
                  AND a.change_case_id_id = NEW.change_case_id_id) <> 1 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_APPROVAL_SNAPSHOT_MISMATCH';
            END IF;
            IF (SELECT COUNT(*) FROM hr_changes_hrchangetransition t
                WHERE t.change_case_id_id = NEW.change_case_id_id
                  AND t.tenant_id = NEW.tenant_id
                  AND t.action = 'approve'
                  AND t.to_status = 'APPROVED_WAITING_EFFECTIVE'
                  AND t.snapshot_hash = NEW.approval_snapshot_hash) <> 1 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_APPROVAL_SNAPSHOT_MISMATCH';
            END IF;
        END
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr06_approval_snapshot_frozen_update
        BEFORE UPDATE ON hr_changes_hrchangeapprovalsnapshot
        FOR EACH ROW
        BEGIN
            IF (SELECT status FROM hr_changes_hrpersonnelchangecase
                WHERE id = OLD.change_case_id_id) <> 'UNDER_APPROVAL' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_APPROVAL_SNAPSHOT_FROZEN';
            END IF;
        END
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr06_approval_snapshot_frozen_delete
        BEFORE DELETE ON hr_changes_hrchangeapprovalsnapshot
        FOR EACH ROW
        BEGIN
            IF (SELECT status FROM hr_changes_hrpersonnelchangecase
                WHERE id = OLD.change_case_id_id) <> 'UNDER_APPROVAL' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_APPROVAL_SNAPSHOT_FROZEN';
            END IF;
        END
        """
    )
    schema_editor.execute(
        "CREATE TRIGGER hr06_transition_no_update BEFORE UPDATE ON "
        "hr_changes_hrchangetransition FOR EACH ROW SIGNAL SQLSTATE '45000' "
        "SET MESSAGE_TEXT = 'HR06_TRANSITION_IMMUTABLE'"
    )
    schema_editor.execute(
        "CREATE TRIGGER hr06_transition_no_delete BEFORE DELETE ON "
        "hr_changes_hrchangetransition FOR EACH ROW SIGNAL SQLSTATE '45000' "
        "SET MESSAGE_TEXT = 'HR06_TRANSITION_IMMUTABLE'"
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER hr06_case_no_fake_effective_insert
        BEFORE INSERT ON {CASE_TABLE}
        FOR EACH ROW
        BEGIN
            IF NEW.status = 'EFFECTIVE' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EFFECTIVE_REQUIRES_TRUSTED_EXECUTION_RECEIPT';
            END IF;
        END
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER hr06_case_trusted_effective_update
        BEFORE UPDATE ON {CASE_TABLE}
        FOR EACH ROW
        BEGIN
            IF NEW.status = 'EFFECTIVE' AND OLD.status <> 'EFFECTIVE' THEN
                IF OLD.status <> 'APPLYING' OR NEW.version <> OLD.version + 1 OR
                   (SELECT COUNT(*) FROM {SNAPSHOT_TABLE} x
                    WHERE x.change_case_id_id = NEW.id AND x.tenant_id = NEW.tenant_id
                      AND x.case_version = NEW.version
                      AND x.provider_code = 'HR06_CANONICAL_HR02_HR03_V1'
                      AND x.provider_receipt_hash REGEXP '^[0-9a-f]{{64}}$') <> 1 THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EFFECTIVE_REQUIRES_TRUSTED_EXECUTION_RECEIPT';
                END IF;
            END IF;
        END
        """
    )


def restore_previous_execution_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    remove_execution_triggers(apps, schema_editor)
    schema_editor.execute(
        f"CREATE TRIGGER {SNAPSHOT_TABLE}_no_update BEFORE UPDATE ON {SNAPSHOT_TABLE} "
        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_EVIDENCE_IMMUTABLE'"
    )
    schema_editor.execute(
        f"CREATE TRIGGER {SNAPSHOT_TABLE}_no_delete BEFORE DELETE ON {SNAPSHOT_TABLE} "
        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_EVIDENCE_IMMUTABLE'"
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER {SNAPSHOT_TABLE}_seal_insert
        BEFORE INSERT ON {SNAPSHOT_TABLE}
        FOR EACH ROW
        BEGIN
            IF NEW.sealed_at IS NULL OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$'
               OR NEW.authority_domain <> 'HR03' OR NEW.authority_contract_version <> 1 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_SEAL_INVALID';
            END IF;
            IF (SELECT COUNT(*) FROM {CASE_TABLE} c
                JOIN hr_staff_hrstaffmaster s ON s.id = c.staff_master_id_id
                WHERE c.id = NEW.change_case_id_id AND c.tenant_id = NEW.tenant_id
                  AND s.tenant_id = NEW.tenant_id) <> 1 THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR06_EXECUTION_PARENT_LINEAGE_INVALID';
            END IF;
        END
        """
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_changes", "0007_hrchangeauthorityreceipt_and_more")]

    operations = [
        migrations.RunPython(remove_execution_triggers, restore_previous_execution_triggers),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="approval_snapshot_hash",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="approval_snapshot_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="case_version",
            field=models.PositiveBigIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="execution_idempotency_key",
            field=models.CharField(blank=True, default="", editable=False, max_length=128),
        ),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="provider_code",
            field=models.CharField(blank=True, default="", editable=False, max_length=40),
        ),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="provider_receipt_hash",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="hrchangeeffectivesnapshot",
            name="provider_receipt_json",
            field=models.JSONField(blank=True, default=dict, editable=False),
        ),
        migrations.RunPython(backfill_trusted_effect_fields, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="hrchangeeffectivesnapshot",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "execution_idempotency_key"),
                name="uq_hr06_effect_idempotency",
            ),
        ),
        migrations.RunPython(install_trusted_execution_triggers, remove_execution_triggers),
    ]
