import hashlib
import json

from django.db import migrations, models


APPEND_ONLY_TABLES = (
    ("hr18_asof_evidence_snapshot", "HR18_ASOF_EVIDENCE_IMMUTABLE"),
    ("hr18_metric_evaluation_snapshot", "HR18_METRIC_EVALUATION_IMMUTABLE"),
    ("hr18_exchange_receipt", "HR18_EXCHANGE_RECEIPT_IMMUTABLE"),
    ("hr18_exchange_reconciliation", "HR18_EXCHANGE_RECONCILIATION_IMMUTABLE"),
)


def _canonical_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def backfill_reconciliation_hashes(apps, schema_editor):
    Reconciliation = apps.get_model("hr_data", "ExchangeReconciliation")
    pending = []
    for row in Reconciliation.objects.all().iterator(chunk_size=500):
        row.reconciliation_hash = _canonical_hash(
            {
                "tenantId": int(row.tenant_id),
                "jobId": str(row.job_id),
                "receiptId": str(row.receipt_id),
                "expectedPayloadHash": row.expected_payload_hash,
                "receivedPayloadHash": row.received_payload_hash,
                "expectedRecordCount": int(row.expected_record_count),
                "receivedRecordCount": row.received_record_count,
                "status": row.status,
                "differences": row.differences_json or {},
                "reconciledAt": row.reconciled_at.isoformat(),
            }
        )
        pending.append(row)
        if len(pending) >= 500:
            Reconciliation.objects.bulk_update(pending, ["reconciliation_hash"])
            pending = []
    if pending:
        Reconciliation.objects.bulk_update(pending, ["reconciliation_hash"])


def install_mysql_evidence_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for table, code in APPEND_ONLY_TABLES:
        update_trigger = f"{table}_no_update"
        delete_trigger = f"{table}_no_delete"
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {update_trigger}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {delete_trigger}")
        schema_editor.execute(
            f"""
            CREATE TRIGGER {update_trigger}
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '{code}: append a new evidence row'
            """
        )
        schema_editor.execute(
            f"""
            CREATE TRIGGER {delete_trigger}
            BEFORE DELETE ON {table}
            FOR EACH ROW
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '{code}: evidence cannot be deleted'
            """
        )

    schema_editor.execute("DROP TRIGGER IF EXISTS hr18_submission_guard_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr18_submission_no_delete")
    schema_editor.execute(
        """
        CREATE TRIGGER hr18_submission_guard_update
        BEFORE UPDATE ON hr18_submission_snapshot
        FOR EACH ROW
        BEGIN
            IF NOT (OLD.tenant_id <=> NEW.tenant_id)
               OR NOT (OLD.submission_no <=> NEW.submission_no)
               OR NOT (OLD.definition_kind <=> NEW.definition_kind)
               OR NOT (OLD.definition_code <=> NEW.definition_code)
               OR NOT (OLD.definition_version <=> NEW.definition_version)
               OR NOT (OLD.as_of_date <=> NEW.as_of_date)
               OR NOT (OLD.scope_json <=> NEW.scope_json)
               OR NOT (OLD.payload_hash <=> NEW.payload_hash)
               OR NOT (OLD.parent_submission_id <=> NEW.parent_submission_id)
               OR NOT (OLD.created_at <=> NEW.created_at)
               OR NOT (OLD.created_by <=> NEW.created_by) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_IDENTITY_IMMUTABLE';
            END IF;

            IF NOT (
                (OLD.status = 'DRAFT' AND NEW.status = 'VALIDATED')
                OR (OLD.status = 'VALIDATED' AND NEW.status = 'APPROVED')
                OR (OLD.status IN ('APPROVED', 'DISPATCH_FAILED') AND NEW.status = 'DISPATCH_QUEUED')
                OR (OLD.status IN ('APPROVED', 'DISPATCH_QUEUED') AND NEW.status = 'DISPATCH_FAILED')
                OR (OLD.status = 'DISPATCH_FAILED' AND NEW.status = 'DISPATCH_FAILED')
                OR (OLD.status = 'DISPATCH_QUEUED' AND NEW.status = 'SUBMITTED')
                OR (OLD.status = 'SUBMITTED' AND NEW.status IN ('ACCEPTED', 'REJECTED'))
                OR (OLD.status IN ('ACCEPTED', 'REJECTED') AND NEW.status = 'CORRECTED')
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_STATE_TRANSITION_INVALID';
            END IF;

            IF NOT (OLD.dispatch_ref <=> NEW.dispatch_ref)
               AND NOT (OLD.status IN ('APPROVED', 'DISPATCH_FAILED') AND NEW.status = 'DISPATCH_QUEUED') THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_DISPATCH_REF_IMMUTABLE';
            END IF;
            IF NOT (OLD.dispatch_requested_at <=> NEW.dispatch_requested_at)
               AND NOT (OLD.status IN ('APPROVED', 'DISPATCH_FAILED') AND NEW.status = 'DISPATCH_QUEUED') THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_DISPATCH_TIME_IMMUTABLE';
            END IF;
            IF NOT (OLD.dispatch_error <=> NEW.dispatch_error)
               AND NOT (
                   NEW.status IN ('DISPATCH_QUEUED', 'DISPATCH_FAILED', 'SUBMITTED')
                   AND OLD.status IN ('APPROVED', 'DISPATCH_FAILED', 'DISPATCH_QUEUED')
               ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_DISPATCH_EVIDENCE_IMMUTABLE';
            END IF;
            IF NOT (OLD.submitted_at <=> NEW.submitted_at)
               AND NOT (OLD.status = 'DISPATCH_QUEUED' AND NEW.status = 'SUBMITTED') THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_SUBMITTED_TIME_IMMUTABLE';
            END IF;
            IF NOT (OLD.receipt_ref <=> NEW.receipt_ref)
               AND NOT (OLD.status = 'SUBMITTED' AND NEW.status IN ('ACCEPTED', 'REJECTED')) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR18_SUBMISSION_RECEIPT_IMMUTABLE';
            END IF;
        END
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr18_submission_no_delete
        BEFORE DELETE ON hr18_submission_snapshot
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'HR18_SUBMISSION_IMMUTABLE: submission history cannot be deleted'
        """
    )


def remove_mysql_evidence_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for table, _code in APPEND_ONLY_TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr18_submission_guard_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr18_submission_no_delete")


class Migration(migrations.Migration):
    # MySQL trigger DDL commits implicitly and is intentionally non-atomic.
    atomic = False

    dependencies = [("hr_data", "0013_legacy_report_takeover")]

    operations = [
        migrations.AddField(
            model_name="exchangereconciliation",
            name="reconciliation_hash",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(
            backfill_reconciliation_hashes,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            install_mysql_evidence_seals,
            remove_mysql_evidence_seals,
        ),
    ]
