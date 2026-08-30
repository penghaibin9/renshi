import hashlib
import json

from django.db import migrations, models


FORMAL_STATUSES = {"EFFECTIVE", "REVISED", "REVOKED"}


def _hash_fact(row):
    payload = {
        "tenantId": int(row.tenant_id),
        "factNo": row.fact_no,
        "personId": str(row.person_id),
        "employmentRelationshipId": str(row.employment_relationship_id),
        "sourceCaseId": str(row.source_case_id),
        "exitType": row.exit_type,
        "employmentEndDate": row.employment_end_date.isoformat(),
        "lastWorkingDate": (
            row.last_working_date.isoformat() if row.last_working_date else None
        ),
        "accessEndAt": row.access_end_at.isoformat() if row.access_end_at else None,
        "status": row.status,
        "effectReceipt": row.effect_receipt_json or {},
        "supersedesFactId": (
            str(row.supersedes_fact_id) if row.supersedes_fact_id else None
        ),
        "changeReason": row.change_reason,
        "evidenceRef": row.evidence_ref,
        "sealedAt": row.sealed_at.isoformat() if row.sealed_at else None,
        "createdBy": row.created_by,
        "updatedBy": row.updated_by,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_existing_formal_facts(apps, schema_editor):
    Fact = apps.get_model("hr_exit", "ExitFact")
    pending = []
    for row in Fact.objects.all().iterator(chunk_size=500):
        if row.status not in FORMAL_STATUSES:
            row.content_hash = ""
            row.sealed_at = None
        else:
            if row.status in {"REVISED", "REVOKED"}:
                if row.supersedes_fact_id is None:
                    raise RuntimeError(
                        "EXIT_FACT_CHAIN_INVALID: legacy revised/revoked fact has no predecessor"
                    )
                row.change_reason = row.change_reason or "LEGACY_MIGRATION"
                row.evidence_ref = row.evidence_ref or "migration://hr16/0010"
            row.sealed_at = row.created_at
            row.content_hash = _hash_fact(row)
        pending.append(row)
        if len(pending) >= 500:
            Fact.objects.bulk_update(
                pending,
                ["change_reason", "evidence_ref", "sealed_at", "content_hash"],
            )
            pending = []
    if pending:
        Fact.objects.bulk_update(
            pending,
            ["change_reason", "evidence_ref", "sealed_at", "content_hash"],
        )


def install_mysql_write_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr16_exit_fact_no_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr16_exit_fact_no_delete")
    schema_editor.execute(
        """
        CREATE TRIGGER hr16_exit_fact_no_update
        BEFORE UPDATE ON hr16_exit_fact
        FOR EACH ROW
        BEGIN
            IF OLD.sealed_at IS NOT NULL THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'EXIT_FACT_IMMUTABLE: append a successor fact';
            END IF;
        END
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr16_exit_fact_no_delete
        BEFORE DELETE ON hr16_exit_fact
        FOR EACH ROW
        BEGIN
            IF OLD.sealed_at IS NOT NULL THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'EXIT_FACT_IMMUTABLE: sealed facts cannot be deleted';
            END IF;
        END
        """
    )


def remove_mysql_write_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr16_exit_fact_no_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr16_exit_fact_no_delete")


class Migration(migrations.Migration):
    # MySQL 8.4 trigger DDL is not rollback-capable.
    atomic = False

    dependencies = [("hr_exit", "0009_retirement_policy_precheck")]

    operations = [
        migrations.AlterModelOptions(
            name="exitcase",
            options={
                "permissions": [
                    ("hr.exit.view", "查看 HR16 退休与离校工作区"),
                    ("hr.exit.manage", "办理 HR16 退休与离校流程"),
                    ("hr.exit.handover", "维护 HR16 离校交接清单"),
                    ("hr.exit.effect", "执行 HR16 正式离校就业关系生效"),
                    ("hr.exit.fact.correct", "更正 HR16 已封板离校正式事实"),
                    ("hr.exit.fact.revoke", "撤销 HR16 已封板离校正式事实"),
                    ("hr.exit.retirement_policy.manage", "维护 HR16 版本化退休政策"),
                    ("hr.exit.retirement_precheck.execute", "执行 HR16 退休日期预审"),
                ]
            },
        ),
        migrations.AlterModelOptions(
            name="exitfact",
            options={"base_manager_name": "objects"},
        ),
        migrations.AddField(
            model_name="exitfact",
            name="change_reason",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="exitfact",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="exitfact",
            name="evidence_ref",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.AddField(
            model_name="exitfact",
            name="sealed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(seal_existing_formal_facts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="exitfact",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "supersedes_fact_id"),
                name="uq_hr16_exit_fact_successor",
            ),
        ),
        migrations.AddConstraint(
            model_name="exitfact",
            constraint=models.CheckConstraint(
                condition=models.Q(("last_working_date__isnull", True))
                | models.Q(("last_working_date__lte", models.F("employment_end_date"))),
                name="ck_hr16_exit_fact_dates",
            ),
        ),
        migrations.AddConstraint(
            model_name="exitfact",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("content_hash", ""),
                    ("sealed_at__isnull", True),
                    ("status", "EFFECT_PENDING"),
                )
                | models.Q(
                    ("content_hash__regex", "^[0-9a-f]{64}$"),
                    ("sealed_at__isnull", False),
                    ("status__in", ("EFFECTIVE", "REVISED", "REVOKED")),
                ),
                name="ck_hr16_exit_fact_seal",
            ),
        ),
        migrations.AddConstraint(
            model_name="exitfact",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status", "EFFECTIVE"), ("supersedes_fact_id__isnull", True)
                )
                | models.Q(
                    ("change_reason__gt", ""),
                    ("evidence_ref__gt", ""),
                    ("status__in", ("REVISED", "REVOKED")),
                    ("supersedes_fact_id__isnull", False),
                )
                | models.Q(
                    ("status", "EFFECT_PENDING"),
                    ("supersedes_fact_id__isnull", True),
                ),
                name="ck_hr16_exit_fact_chain",
            ),
        ),
        migrations.RunPython(install_mysql_write_seal, remove_mysql_write_seal),
    ]
