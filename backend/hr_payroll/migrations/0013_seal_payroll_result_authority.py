from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from django.db import migrations, models
from django.db.models import Count


TERMINAL = {"FINALIZED", "ADJUSTED", "REVERSED"}
TABLE = "hr15_payroll_result_fact"


def _hash(row, effective_at):
    payload = {
        "tenantId": int(row.tenant_id),
        "resultNo": row.result_no,
        "payrollPeriodId": str(row.payroll_period_id),
        "staffId": str(row.staff_id),
        "currencyCode": row.currency_code,
        "grossAmount": str(row.gross_amount),
        "deductionAmount": str(row.deduction_amount),
        "netAmount": str(row.net_amount),
        "status": row.status,
        "supersedesResultId": str(row.supersedes_result_id) if row.supersedes_result_id else None,
        "authorityReason": row.authority_reason or "",
        "authorityEvidenceRef": row.authority_evidence_ref or "",
        "authorityActorId": row.authority_actor_id,
        "effectiveAt": effective_at.isoformat() if effective_at else None,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def backfill_seals(apps, schema_editor):
    Result = apps.get_model("hr_payroll", "PayrollResultFact")
    Period = apps.get_model("hr_payroll", "PayrollPeriod")

    branches = list(
        Result.objects.exclude(supersedes_result_id__isnull=True)
        .values("tenant_id", "supersedes_result_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)[:20]
    )
    if branches:
        raise RuntimeError("HR15_RESULT_BRANCH_CONFLICT: resolve duplicate successors before migration")

    terminal_rows = list(
        Result.objects.filter(status__in=TERMINAL).values(
            "id", "tenant_id", "payroll_period_id", "staff_id", "currency_code",
            "status", "supersedes_result_id"
        )
    )
    terminal_by_id = {row["id"]: row for row in terminal_rows}
    for row in terminal_rows:
        if row["status"] == "FINALIZED" and row["supersedes_result_id"]:
            raise RuntimeError(f"HR15_FINALIZED_RESULT_CANNOT_SUPERSEDE:{row['id']}")
        if row["status"] in {"ADJUSTED", "REVERSED"} and not row["supersedes_result_id"]:
            raise RuntimeError(f"HR15_DERIVED_RESULT_SOURCE_REQUIRED:{row['id']}")
        if row["supersedes_result_id"]:
            parent = terminal_by_id.get(row["supersedes_result_id"])
            if parent is None:
                raise RuntimeError(f"HR15_RESULT_PREDECESSOR_MISSING:{row['id']}")
            if (
                int(parent["tenant_id"]) != int(row["tenant_id"])
                or parent["payroll_period_id"] != row["payroll_period_id"]
                or parent["staff_id"] != row["staff_id"]
                or parent["currency_code"] != row["currency_code"]
            ):
                raise RuntimeError(f"HR15_RESULT_CHAIN_IDENTITY_MISMATCH:{row['id']}")
    for row in terminal_rows:
        seen = set()
        cursor = row
        while cursor.get("supersedes_result_id"):
            if cursor["id"] in seen:
                raise RuntimeError(f"HR15_RESULT_CHAIN_CYCLE:{row['id']}")
            seen.add(cursor["id"])
            cursor = terminal_by_id.get(cursor["supersedes_result_id"])
            if cursor is None:
                break
        if cursor is not None and cursor["status"] != "FINALIZED":
            raise RuntimeError(f"HR15_RESULT_CHAIN_ROOT_INVALID:{row['id']}")

    period_map = {
        (int(row["tenant_id"]), row["id"]): row
        for row in Period.objects.values("id", "tenant_id", "finalized_at")
    }
    for row in Result.objects.filter(status__in=TERMINAL).iterator(chunk_size=500):
        if Decimal(row.net_amount) != Decimal(row.gross_amount) - Decimal(row.deduction_amount):
            raise RuntimeError(f"HR15_RESULT_ARITHMETIC_INVALID:{row.pk}")
        if row.status == "FINALIZED":
            period = period_map.get((int(row.tenant_id), row.payroll_period_id))
            effective_at = (period or {}).get("finalized_at") or row.updated_at or row.created_at
        else:
            effective_at = row.created_at or row.updated_at
        if not effective_at:
            raise RuntimeError(f"HR15_RESULT_EFFECTIVE_TIME_MISSING:{row.pk}")
        if row.status in {"ADJUSTED", "REVERSED"} and not (row.authority_reason or "").strip():
            row.authority_reason = "MIGRATED_LEGACY_DERIVED_RESULT"
        Result.objects.filter(pk=row.pk).update(
            authority_reason=row.authority_reason,
            effective_at=effective_at,
            sealed_at=effective_at,
            content_hash=_hash(row, effective_at),
        )


def create_mysql_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    statements = [
        "DROP TRIGGER IF EXISTS hr15_payroll_result_bi_seal",
        "DROP TRIGGER IF EXISTS hr15_payroll_result_bu_seal",
        "DROP TRIGGER IF EXISTS hr15_payroll_result_bd_seal",
        f"""
        CREATE TRIGGER hr15_payroll_result_bi_seal
        BEFORE INSERT ON {TABLE}
        FOR EACH ROW
        BEGIN
            IF NEW.status IN ('FINALIZED','ADJUSTED','REVERSED') THEN
                IF NEW.effective_at IS NULL OR NEW.sealed_at IS NULL
                   OR NEW.content_hash IS NULL OR CHAR_LENGTH(NEW.content_hash) <> 64 THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_PAYROLL_RESULT_SEAL_REQUIRED';
                END IF;
                IF NEW.status = 'FINALIZED' AND NEW.supersedes_result_id IS NOT NULL THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_FINALIZED_RESULT_CANNOT_SUPERSEDE';
                END IF;
                IF NEW.status IN ('ADJUSTED','REVERSED') AND NEW.supersedes_result_id IS NULL THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_DERIVED_RESULT_SOURCE_REQUIRED';
                END IF;
                IF NEW.status IN ('ADJUSTED','REVERSED') AND (NEW.authority_reason IS NULL OR CHAR_LENGTH(TRIM(NEW.authority_reason)) = 0) THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_DERIVED_RESULT_REASON_REQUIRED';
                END IF;
            END IF;
        END
        """,
        f"""
        CREATE TRIGGER hr15_payroll_result_bu_seal
        BEFORE UPDATE ON {TABLE}
        FOR EACH ROW
        BEGIN
            IF OLD.status IN ('FINALIZED','ADJUSTED','REVERSED') THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PAYROLL_FINAL_RESULT_IMMUTABLE';
            END IF;
            IF NEW.status IN ('ADJUSTED','REVERSED') THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_DERIVED_RESULT_MUST_BE_APPENDED';
            END IF;
            IF NEW.status = 'FINALIZED' THEN
                IF NEW.effective_at IS NULL OR NEW.sealed_at IS NULL
                   OR NEW.content_hash IS NULL OR CHAR_LENGTH(NEW.content_hash) <> 64 THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_PAYROLL_RESULT_SEAL_REQUIRED';
                END IF;
                IF NOT (
                    OLD.tenant_id <=> NEW.tenant_id
                    AND OLD.result_no <=> NEW.result_no
                    AND OLD.payroll_period_id <=> NEW.payroll_period_id
                    AND OLD.staff_id <=> NEW.staff_id
                    AND OLD.currency_code <=> NEW.currency_code
                    AND OLD.gross_amount <=> NEW.gross_amount
                    AND OLD.deduction_amount <=> NEW.deduction_amount
                    AND OLD.net_amount <=> NEW.net_amount
                    AND OLD.supersedes_result_id <=> NEW.supersedes_result_id
                    AND OLD.authority_reason <=> NEW.authority_reason
                    AND OLD.authority_evidence_ref <=> NEW.authority_evidence_ref
                    AND OLD.authority_actor_id <=> NEW.authority_actor_id
                ) THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'HR15_FINALIZATION_PAYLOAD_CHANGED';
                END IF;
            END IF;
        END
        """,
        f"""
        CREATE TRIGGER hr15_payroll_result_bd_seal
        BEFORE DELETE ON {TABLE}
        FOR EACH ROW
        BEGIN
            IF OLD.status IN ('FINALIZED','ADJUSTED','REVERSED') THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PAYROLL_FINAL_RESULT_IMMUTABLE';
            END IF;
        END
        """,
    ]
    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def drop_mysql_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        for name in (
            "hr15_payroll_result_bi_seal",
            "hr15_payroll_result_bu_seal",
            "hr15_payroll_result_bd_seal",
        ):
            cursor.execute(f"DROP TRIGGER IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [("hr_payroll", "0012_compensation_change_cases")]

    operations = [
        migrations.AddField(
            model_name="payrollresultfact",
            name="authority_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="payrollresultfact",
            name="authority_evidence_ref",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="payrollresultfact",
            name="authority_actor_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payrollresultfact",
            name="effective_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payrollresultfact",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="payrollresultfact",
            name="sealed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_seals, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="payrollresultfact",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "supersedes_result_id"),
                name="uq_hr15_result_single_successor",
            ),
        ),
        migrations.AddIndex(
            model_name="payrollresultfact",
            index=models.Index(fields=("tenant_id", "effective_at"), name="idx_hr15_result_effective"),
        ),
        migrations.RunPython(create_mysql_triggers, drop_mysql_triggers),
    ]
