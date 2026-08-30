import hashlib
import json

from django.db import migrations, models
from django.db.models import F, Q


def _hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _policy_payload(row):
    return {
        "tenantId": int(row.tenant_id),
        "policyCode": row.policy_code,
        "versionNo": row.version_no,
        "name": row.name,
        "titleSeriesCode": row.title_series_code,
        "titleLevelCode": row.title_level_code,
        "trackCode": row.track_code,
        "requiredBallots": row.required_ballots,
        "requiredPassVotes": row.required_pass_votes,
        "effectiveFrom": row.effective_from.isoformat(),
        "effectiveTo": row.effective_to.isoformat() if row.effective_to else None,
        "publishedAt": row.published_at.isoformat() if row.published_at else None,
        "status": row.status,
    }


def _result_payload(row):
    return {
        "tenantId": int(row.tenant_id),
        "resultNo": row.result_no,
        "personId": str(row.person_id),
        "applicationCaseId": str(row.application_case_id),
        "titleCode": row.title_code,
        "titleName": row.title_name,
        "titleSeriesCode": row.title_series_code,
        "titleLevelCode": row.title_level_code,
        "effectiveFrom": row.effective_from.isoformat(),
        "effectiveTo": row.effective_to.isoformat() if row.effective_to else None,
        "status": row.status,
        "supersedesResultId": (
            str(row.supersedes_result_id) if row.supersedes_result_id else None
        ),
        "authoritySnapshot": row.authority_snapshot_json,
        "sealedAt": row.sealed_at.isoformat() if row.sealed_at else None,
        "createdBy": row.created_by,
        "updatedBy": row.updated_by,
    }


def _legacy_result_payload(row):
    payload = _result_payload(row)
    payload.pop("authoritySnapshot", None)
    return payload


def _legacy_policy_payload(row):
    payload = _policy_payload(row)
    payload.pop("requiredBallots", None)
    payload.pop("requiredPassVotes", None)
    return payload


def drop_mysql_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for name in (
        "hr13_title_result_no_update",
        "hr13_title_result_no_delete",
        "hr13_review_ballot_no_update",
        "hr13_review_ballot_no_delete",
        "hr13_review_ballot_insert_guard",
        "hr13_review_round_insert_guard",
        "hr13_review_round_write_seal_upd",
        "hr13_review_round_write_seal_del",
        "hr13_title_policy_no_update",
        "hr13_title_policy_no_delete",
        "hr13_title_application_identity_upd",
        "hr13_title_application_no_delete",
    ):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name}")


def restore_legacy_result_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_title_result_no_update
        BEFORE UPDATE ON hr13_professional_title_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_RESULT_IMMUTABLE: append a successor fact'
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_title_result_no_delete
        BEFORE DELETE ON hr13_professional_title_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_RESULT_IMMUTABLE: formal facts cannot be deleted'
        """
    )


def backfill_hashes(apps, schema_editor):
    Policy = apps.get_model("hr_title", "TitlePolicyVersion")
    Result = apps.get_model("hr_title", "ProfessionalTitleResult")
    for row in Policy.objects.filter(status="PUBLISHED", published_at__isnull=False).iterator():
        row.content_hash = _hash(_policy_payload(row))
        row.save(update_fields=["content_hash"])
    for row in Result.objects.all().iterator():
        row.content_hash = _hash(_result_payload(row))
        row.save(update_fields=["content_hash"])


def reverse_hashes(apps, schema_editor):
    Policy = apps.get_model("hr_title", "TitlePolicyVersion")
    Result = apps.get_model("hr_title", "ProfessionalTitleResult")
    for row in Policy.objects.filter(status="PUBLISHED", published_at__isnull=False).iterator():
        row.content_hash = _hash(_legacy_policy_payload(row))
        row.save(update_fields=["content_hash"])
    for row in Result.objects.all().iterator():
        row.content_hash = _hash(_legacy_result_payload(row))
        row.save(update_fields=["content_hash"])


def install_mysql_seals(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    drop_mysql_seals(apps, schema_editor)
    statements = (
        """
        CREATE TRIGGER hr13_title_result_no_update
        BEFORE UPDATE ON hr13_professional_title_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_RESULT_IMMUTABLE: append a successor fact'
        """,
        """
        CREATE TRIGGER hr13_title_result_no_delete
        BEFORE DELETE ON hr13_professional_title_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_RESULT_IMMUTABLE: formal facts cannot be deleted'
        """,
        """
        CREATE TRIGGER hr13_review_ballot_no_update
        BEFORE UPDATE ON hr13_title_review_ballot
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_REVIEW_BALLOT_IMMUTABLE: submitted ballots cannot be updated'
        """,
        """
        CREATE TRIGGER hr13_review_ballot_no_delete
        BEFORE DELETE ON hr13_title_review_ballot
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_REVIEW_BALLOT_APPEND_ONLY: submitted ballots cannot be deleted'
        """,
        """
        CREATE TRIGGER hr13_review_ballot_insert_guard
        BEFORE INSERT ON hr13_title_review_ballot
        FOR EACH ROW
        BEGIN
          DECLARE valid_parent_count INT DEFAULT 0;
          SELECT COUNT(*) INTO valid_parent_count
          FROM hr13_title_review_round r
          JOIN hr13_title_review_assignment a
            ON a.id = NEW.assignment_id
           AND a.tenant_id = NEW.tenant_id
           AND a.review_round_id = NEW.review_round_id
           AND a.application_case_id = r.application_case_id
          WHERE r.id = NEW.review_round_id
            AND r.tenant_id = NEW.tenant_id
            AND r.status = 'OPEN'
            AND a.status = 'ACCEPTED'
            AND a.conflict_declared = 0
            AND NOT EXISTS (
              SELECT 1 FROM hr13_title_review_assignment successor
              WHERE successor.tenant_id = NEW.tenant_id
                AND successor.supersedes_assignment_id = a.id
            );
          IF valid_parent_count <> 1 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_REVIEW_BALLOT_PARENT_INVALID: open eligible assignment required';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr13_review_round_insert_guard
        BEFORE INSERT ON hr13_title_review_round
        FOR EACH ROW
        BEGIN
          IF NEW.status <> 'OPEN'
             OR NEW.closed_at IS NOT NULL
             OR NEW.closed_by IS NOT NULL
             OR JSON_LENGTH(NEW.closure_snapshot_json) <> 0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_REVIEW_ROUND_SERVICE_REQUIRED: rounds must start open';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr13_review_round_write_seal_upd
        BEFORE UPDATE ON hr13_title_review_round
        FOR EACH ROW
        BEGIN
          IF OLD.tenant_id <> NEW.tenant_id
             OR OLD.round_no <> NEW.round_no
             OR OLD.application_case_id <> NEW.application_case_id
             OR OLD.attempt_no <> NEW.attempt_no
             OR OLD.required_ballots <> NEW.required_ballots
             OR OLD.required_pass_votes <> NEW.required_pass_votes
             OR NOT (OLD.opened_by <=> NEW.opened_by)
             OR OLD.status <> 'OPEN' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_REVIEW_ROUND_IMMUTABLE: frozen review facts cannot be updated';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr13_review_round_write_seal_del
        BEFORE DELETE ON hr13_title_review_round
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_REVIEW_ROUND_APPEND_ONLY: review facts cannot be deleted'
        """,
        """
        CREATE TRIGGER hr13_title_policy_no_update
        BEFORE UPDATE ON hr13_title_policy_version
        FOR EACH ROW
        BEGIN
          IF OLD.status = 'PUBLISHED' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_POLICY_IMMUTABLE: published title rules cannot be updated';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr13_title_policy_no_delete
        BEFORE DELETE ON hr13_title_policy_version
        FOR EACH ROW
        BEGIN
          IF OLD.status = 'PUBLISHED' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_POLICY_IMMUTABLE: published title rules cannot be deleted';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr13_title_application_identity_upd
        BEFORE UPDATE ON hr13_title_application_case
        FOR EACH ROW
        BEGIN
          IF OLD.status <> 'DRAFT' AND (
             OLD.tenant_id <> NEW.tenant_id
             OR OLD.case_no <> NEW.case_no
             OR OLD.person_id <> NEW.person_id
             OR OLD.policy_version_id <> NEW.policy_version_id
             OR OLD.batch_no <> NEW.batch_no
             OR OLD.requested_title_code <> NEW.requested_title_code
             OR OLD.requested_title_name <> NEW.requested_title_name
          ) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_APPLICATION_IDENTITY_IMMUTABLE: submitted identity is frozen';
          END IF;
        END
        """,
        """
        CREATE TRIGGER hr13_title_application_no_delete
        BEFORE DELETE ON hr13_title_application_case
        FOR EACH ROW
        BEGIN
          IF OLD.status <> 'DRAFT' THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'TITLE_APPLICATION_APPEND_ONLY: submitted applications cannot be deleted';
          END IF;
        END
        """,
    )
    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("hr_title", "0009_review_assignment_replacement_lineage")]

    operations = [
        migrations.RunPython(drop_mysql_seals, restore_legacy_result_seals),
        migrations.AddField(
            model_name="titlepolicyversion",
            name="required_ballots",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="titlepolicyversion",
            name="required_pass_votes",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="professionaltitleresult",
            name="authority_snapshot_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name="titlepolicyversion",
            constraint=models.CheckConstraint(
                condition=Q(required_ballots__gte=1),
                name="ck_hr13_policy_ballots_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="titlepolicyversion",
            constraint=models.CheckConstraint(
                condition=Q(required_pass_votes__gte=1)
                & Q(required_pass_votes__lte=F("required_ballots")),
                name="ck_hr13_policy_pass_threshold",
            ),
        ),
        migrations.RunPython(backfill_hashes, reverse_hashes),
        migrations.RunPython(install_mysql_seals, drop_mysql_seals),
    ]
