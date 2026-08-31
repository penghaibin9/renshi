import hashlib
import json

from django.db import migrations, models
from django.db.models import F, Q

import hr_assessment.models.result


SEALED_TABLES = (
    ("hr_assessment_final_result", "HR12_FINAL_RESULT_IMMUTABLE"),
    ("hr_assessment_result_revision", "HR12_RESULT_REVISION_IMMUTABLE"),
)


def _hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def backfill_result_seals(apps, schema_editor):
    Result = apps.get_model("hr_assessment", "HrFinalAssessmentResult")
    Revision = apps.get_model("hr_assessment", "HrResultRevision")

    result_batch = []
    for row in Result.objects.all().iterator(chunk_size=500):
        row.finalized_at = row.finalized_at or row.updated_at or row.created_at
        row.sealed_at = row.finalized_at
        row.content_hash = _hash(
            {
                "tenantId": int(row.tenant_id),
                "caseId": str(row.case_id),
                "assessmentType": row.assessment_type,
                "cycleId": str(row.cycle_id) if row.cycle_id else None,
                "gradeCode": row.grade_code,
                "displayGrade": row.display_grade_snapshot_json or {},
                "calculatedScore": (
                    str(row.calculated_score)
                    if row.calculated_score is not None
                    else None
                ),
                "decisionReason": row.decision_reason or "",
                "policyVersionId": (
                    str(row.policy_version_id) if row.policy_version_id else None
                ),
                "decisionSessionId": (
                    str(row.decision_session_id) if row.decision_session_id else None
                ),
                "finalizedAt": row.finalized_at.isoformat(),
                "finalizedBy": str(row.finalized_by) if row.finalized_by else None,
                "resultVersionNo": int(row.result_version_no),
                "status": row.status,
            }
        )
        result_batch.append(row)
        if len(result_batch) >= 500:
            Result.objects.bulk_update(
                result_batch, ["finalized_at", "sealed_at", "content_hash"]
            )
            result_batch = []
    if result_batch:
        Result.objects.bulk_update(
            result_batch, ["finalized_at", "sealed_at", "content_hash"]
        )

    revision_batch = []
    for row in Revision.objects.all().iterator(chunk_size=500):
        row.correction_no = f"LEGACY-{row.id}"
        row.effective_at = row.effective_at or row.updated_at or row.created_at
        row.sealed_at = row.effective_at
        row.content_hash = _hash(
            {
                "tenantId": int(row.tenant_id),
                "resultId": str(row.result_id),
                "correctionNo": row.correction_no,
                "previousVersion": int(row.previous_version),
                "newVersion": int(row.new_version),
                "revisionType": row.revision_type,
                "reason": row.reason,
                "authorityStaffId": (
                    str(row.authority_staff_id) if row.authority_staff_id else None
                ),
                "before": row.before_snapshot_json or {},
                "after": row.after_snapshot_json or {},
                "effectiveAt": row.effective_at.isoformat(),
            }
        )
        revision_batch.append(row)
        if len(revision_batch) >= 500:
            Revision.objects.bulk_update(
                revision_batch,
                [
                    "correction_no",
                    "effective_at",
                    "sealed_at",
                    "content_hash",
                ],
            )
            revision_batch = []
    if revision_batch:
        Revision.objects.bulk_update(
            revision_batch,
            ["correction_no", "effective_at", "sealed_at", "content_hash"],
        )


def install_mysql_result_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for table, code in SEALED_TABLES:
        insert_trigger = f"{table}_seal_insert"
        update_trigger = f"{table}_no_update"
        delete_trigger = f"{table}_no_delete"
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {insert_trigger}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {update_trigger}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {delete_trigger}")
        schema_editor.execute(
            f"""
            CREATE TRIGGER {insert_trigger}
            BEFORE INSERT ON {table}
            FOR EACH ROW
            BEGIN
                IF NEW.sealed_at IS NULL
                   OR NEW.content_hash NOT REGEXP '^[0-9a-f]{{64}}$' THEN
                    SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = '{code}: sealed_at and SHA-256 are required';
                END IF;
            END
            """
        )
        schema_editor.execute(
            f"""
            CREATE TRIGGER {update_trigger}
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '{code}: append a correction fact'
            """
        )
        schema_editor.execute(
            f"""
            CREATE TRIGGER {delete_trigger}
            BEFORE DELETE ON {table}
            FOR EACH ROW
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '{code}: formal facts cannot be deleted'
            """
        )


def remove_mysql_result_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for table, _code in SEALED_TABLES:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_seal_insert")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")


class Migration(migrations.Migration):
    # MySQL CREATE/DROP TRIGGER is not rollback-safe and implicitly commits.
    atomic = False

    dependencies = [("hr_assessment", "0011_legacy_pms_writer_seal")]

    operations = [
        migrations.AddField(
            model_name="hrfinalassessmentresult",
            name="sealed_at",
            field=models.DateTimeField(null=True, verbose_name="封板时间"),
        ),
        migrations.AddField(
            model_name="hrresultrevision",
            name="content_hash",
            field=models.CharField(default="", max_length=64, verbose_name="内容哈希"),
        ),
        migrations.AddField(
            model_name="hrresultrevision",
            name="correction_no",
            field=models.CharField(max_length=80, null=True, verbose_name="更正幂等编号"),
        ),
        migrations.AddField(
            model_name="hrresultrevision",
            name="sealed_at",
            field=models.DateTimeField(null=True, verbose_name="封板时间"),
        ),
        migrations.RunPython(
            backfill_result_seals,
            migrations.RunPython.noop,
            atomic=True,
        ),
        migrations.AlterField(
            model_name="hrfinalassessmentresult",
            name="sealed_at",
            field=models.DateTimeField(verbose_name="封板时间"),
        ),
        migrations.AlterField(
            model_name="hrresultrevision",
            name="correction_no",
            field=models.CharField(
                default=hr_assessment.models.result.default_correction_no,
                max_length=80,
                verbose_name="更正幂等编号",
            ),
        ),
        migrations.AlterField(
            model_name="hrresultrevision",
            name="sealed_at",
            field=models.DateTimeField(verbose_name="封板时间"),
        ),
        migrations.AddConstraint(
            model_name="hrresultrevision",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "correction_no"),
                name="hr12_revision_tenant_correction_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrresultrevision",
            constraint=models.UniqueConstraint(
                fields=("result", "new_version"),
                name="hr12_revision_result_version_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="hrresultrevision",
            constraint=models.CheckConstraint(
                condition=Q(new_version__gt=F("previous_version")),
                name="hr12_revision_version_forward_ck",
            ),
        ),
        migrations.RunPython(
            install_mysql_result_seals,
            remove_mysql_result_seals,
            atomic=False,
        ),
    ]
