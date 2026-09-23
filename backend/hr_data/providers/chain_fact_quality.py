"""Integrity quality providers for HR06 execution and HR12 result chains."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from hr_data.services.source_gate import SourceStatus


_PROVIDER_VERSIONS = {
    "HR06": "hr06-change-chain-quality-v1",
    "HR12": "hr12-result-chain-quality-v1",
}
_SUPPORTED_RULES = {
    "HR06": {"HR06_CHANGE_CHAIN_INTEGRITY"},
    "HR12": {"HR12_RESULT_REVISION_CHAIN_INTEGRITY"},
}


def _model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _sid(value) -> str:
    return "" if value in (None, "") else str(value)


def _valid_hash(value) -> bool:
    value = str(value or "").lower()
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()




def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _hr06_snapshot_hash(row: dict) -> str:
    payload = {
        "tenantId": int(row.get("tenant_id") or 0),
        "changeCaseId": _sid(row.get("change_case_id")),
        "staffId": _sid(row.get("change_case_id__staff_master_id")),
        "appliedAt": _iso(row.get("applied_at")),
        "effectiveAt": _iso(row.get("effective_at")),
        "before": row.get("before_json") or {},
        "after": row.get("after_json") or {},
        "sourceFactIds": row.get("source_fact_ids_json") or [],
        "targetFactIds": row.get("target_fact_ids_json") or [],
        "positionChanges": row.get("position_changes_json") or {},
        "downstreamPlanVersion": int(row.get("downstream_plan_version") or 0),
        "legacyChecksum": row.get("checksum") or "",
        "authorityDomain": row.get("authority_domain") or "",
        "authorityContractVersion": int(row.get("authority_contract_version") or 0),
        "caseVersion": int(row.get("case_version") or 0),
        "approvalSnapshotId": _sid(row.get("approval_snapshot_id")) or None,
        "approvalSnapshotHash": row.get("approval_snapshot_hash") or "",
        "providerCode": row.get("provider_code") or "",
        "providerReceipt": row.get("provider_receipt_json") or {},
        "providerReceiptHash": row.get("provider_receipt_hash") or "",
        "executionIdempotencyKey": row.get("execution_idempotency_key") or "",
    }
    return _canonical_hash(payload)


def _hr06_receipt_hash(row: dict) -> str:
    payload = {
        "tenantId": int(row.get("tenant_id") or 0),
        "changeCaseId": _sid(row.get("change_case_id")),
        "effectiveSnapshotId": _sid(row.get("effective_snapshot_id")) or None,
        "sequenceNo": int(row.get("sequence_no") or 0),
        "kind": row.get("kind"),
        "authorityEffect": bool(row.get("authority_effect")),
        "providerCode": row.get("provider_code"),
        "providerCaseId": _sid(row.get("provider_case_id")) or None,
        "providerCaseVersion": row.get("provider_case_version"),
        "providerSnapshotHash": row.get("provider_snapshot_hash") or "",
        "sourceRecordId": _sid(row.get("source_record_id")),
        "idempotencyKey": row.get("idempotency_key"),
        "payload": row.get("payload_json") or {},
        "effectiveAt": _iso(row.get("effective_at")),
    }
    return _canonical_hash(payload)

def _fingerprint(*, rule_code: str, source_ref: str, issue: str) -> str:
    return hashlib.sha256(f"{rule_code}:{source_ref}:{issue}".encode("utf-8")).hexdigest()


def _finding(*, rule_code: str, source_ref: str, issue: str, **details):
    return {
        "sourceObjectRef": source_ref,
        "fingerprint": _fingerprint(
            rule_code=rule_code, source_ref=source_ref, issue=issue
        ),
        "details": {"issue": issue, **details},
    }


def _evidence_hash(*, provider_version: str, tenant_id: int, rule_code: str, as_of_date, rows):
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "providerVersion": provider_version,
                "tenantId": tenant_id,
                "ruleCode": rule_code,
                "asOfDate": as_of_date.isoformat() if isinstance(as_of_date, date) else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")
    for row in rows:
        digest.update(
            json.dumps(
                row,
                cls=DjangoJSONEncoder,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _hr06_quality(*, tenant_id: int, rule_code: str, as_of_date=None):
    snapshot_model = _model("hr_changes", "HrChangeEffectiveSnapshot")
    receipt_model = _model("hr_changes", "HrChangeAuthorityReceipt")
    if snapshot_model is None or receipt_model is None:
        return None

    snapshots = snapshot_model.objects.filter(tenant_id=tenant_id)
    receipts = receipt_model.objects.filter(tenant_id=tenant_id)
    if as_of_date is not None:
        snapshots = snapshots.filter(effective_at__lte=as_of_date)
        receipts = receipts.filter(effective_at__date__lte=as_of_date)

    snapshot_rows = list(
        snapshots.order_by("id").values(
            "id",
            "tenant_id",
            "change_case_id",
            "change_case_id__tenant_id",
            "change_case_id__staff_master_id__tenant_id",
            "change_case_id__staff_master_id",
            "applied_at",
            "effective_at",
            "before_json",
            "after_json",
            "source_fact_ids_json",
            "target_fact_ids_json",
            "position_changes_json",
            "downstream_plan_version",
            "checksum",
            "authority_domain",
            "authority_contract_version",
            "case_version",
            "approval_snapshot_id",
            "approval_snapshot_hash",
            "provider_code",
            "provider_receipt_json",
            "provider_receipt_hash",
            "execution_idempotency_key",
            "content_hash",
        )
    )
    receipt_rows = list(
        receipts.order_by("change_case_id", "sequence_no", "id").values(
            "id",
            "tenant_id",
            "change_case_id",
            "change_case__tenant_id",
            "effective_snapshot_id",
            "effective_snapshot__tenant_id",
            "effective_snapshot__change_case_id",
            "sequence_no",
            "kind",
            "authority_effect",
            "provider_code",
            "provider_case_id",
            "provider_case_version",
            "provider_snapshot_hash",
            "source_record_id",
            "idempotency_key",
            "payload_json",
            "effective_at",
            "content_hash",
        )
    )

    findings = []
    snapshot_by_case = {}
    for row in snapshot_rows:
        source_ref = f"change-snapshot:{row['id']}"
        case_id = _sid(row.get("change_case_id"))
        snapshot_by_case[case_id] = row
        if (
            int(row.get("change_case_id__tenant_id") or 0) != tenant_id
            or int(row.get("change_case_id__staff_master_id__tenant_id") or 0) != tenant_id
        ):
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="CROSS_TENANT_EXECUTION_LINEAGE", changeCaseId=case_id,
            ))
        if row.get("provider_code") != "HR06_CANONICAL_HR02_HR03_V1":
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="EXECUTION_PROVIDER_INVALID", providerCode=row.get("provider_code"),
            ))
        provider_receipt_hash = row.get("provider_receipt_hash")
        expected_provider_receipt_hash = _canonical_hash(row.get("provider_receipt_json") or {})
        if (
            not _valid_hash(provider_receipt_hash)
            or provider_receipt_hash != expected_provider_receipt_hash
        ):
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="EXECUTION_RECEIPT_HASH_INVALID",
            ))
        if (
            not _valid_hash(row.get("content_hash"))
            or row.get("content_hash") != _hr06_snapshot_hash(row)
        ):
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="EXECUTION_CONTENT_HASH_INVALID",
            ))

    by_case = defaultdict(list)
    for row in receipt_rows:
        by_case[_sid(row.get("change_case_id"))].append(row)

    for case_id, rows in by_case.items():
        expected_sequence = 1
        rescinded = False
        for row in rows:
            source_ref = f"change-receipt:{row['id']}"
            if int(row.get("change_case__tenant_id") or 0) != tenant_id:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="CROSS_TENANT_RECEIPT_LINEAGE", changeCaseId=case_id,
                ))
            snapshot_case_id = _sid(row.get("effective_snapshot__change_case_id"))
            if not row.get("effective_snapshot_id"):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="RECEIPT_EXECUTION_SNAPSHOT_REQUIRED", changeCaseId=case_id,
                ))
            elif (
                int(row.get("effective_snapshot__tenant_id") or 0) != tenant_id
                or snapshot_case_id != case_id
            ):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="RECEIPT_SNAPSHOT_LINEAGE_MISMATCH", changeCaseId=case_id,
                ))
            if int(row.get("sequence_no") or 0) != expected_sequence:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=f"change-case:{case_id}",
                    issue="RECEIPT_SEQUENCE_GAP", expected=expected_sequence,
                    actual=row.get("sequence_no"),
                ))
                expected_sequence = int(row.get("sequence_no") or expected_sequence)
            expected_sequence += 1
            if (
                not _valid_hash(row.get("content_hash"))
                or row.get("content_hash") != _hr06_receipt_hash(row)
            ):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="RECEIPT_CONTENT_HASH_INVALID",
                ))
            kind = str(row.get("kind") or "")
            if rescinded:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="RECEIPT_AFTER_RESCIND", changeCaseId=case_id,
                ))
            if kind == "CORRECTION":
                if (
                    not bool(row.get("authority_effect"))
                    or row.get("provider_code") != "HR03_FORMAL_CORRECTION"
                    or not row.get("provider_case_id")
                    or not row.get("provider_case_version")
                    or not _valid_hash(row.get("provider_snapshot_hash"))
                ):
                    findings.append(_finding(
                        rule_code=rule_code, source_ref=source_ref,
                        issue="CORRECTION_AUTHORITY_RECEIPT_INVALID",
                    ))
            elif kind == "ORCHESTRATION_RESCIND":
                rescinded = True
                if (
                    bool(row.get("authority_effect"))
                    or row.get("provider_code") != "HR06_ORCHESTRATION_ONLY"
                    or row.get("provider_case_id")
                    or row.get("provider_case_version")
                ):
                    findings.append(_finding(
                        rule_code=rule_code, source_ref=source_ref,
                        issue="RESCIND_AUTHORITY_RECEIPT_INVALID",
                    ))
            else:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="RECEIPT_KIND_INVALID", kind=kind,
                ))
        if case_id not in snapshot_by_case:
            findings.append(_finding(
                rule_code=rule_code, source_ref=f"change-case:{case_id}",
                issue="RECEIPT_EXECUTION_SNAPSHOT_MISSING",
            ))

    evidence_rows = [
        {"kind": "execution", **row} for row in snapshot_rows
    ] + [
        {"kind": "authorityReceipt", **row} for row in receipt_rows
    ]
    return findings, evidence_rows


def _hr12_base_snapshot(row: dict) -> dict:
    return {
        "sourceResultId": _sid(row.get("id")),
        "sourceContentHash": row.get("content_hash"),
        "version": int(row.get("result_version_no") or 0),
        "status": row.get("status"),
        "gradeCode": row.get("grade_code"),
        "displayGrade": row.get("display_grade_snapshot_json") or {},
        "calculatedScore": (
            str(row.get("calculated_score"))
            if row.get("calculated_score") is not None
            else None
        ),
        "decisionReason": row.get("decision_reason") or "",
    }


def _hr12_result_hash(row: dict) -> str:
    payload = {
        "tenantId": int(row.get("tenant_id") or 0),
        "caseId": _sid(row.get("case_id")),
        "assessmentType": row.get("assessment_type"),
        "cycleId": _sid(row.get("cycle_id")) or None,
        "gradeCode": row.get("grade_code"),
        "displayGrade": row.get("display_grade_snapshot_json") or {},
        "calculatedScore": (
            str(row.get("calculated_score"))
            if row.get("calculated_score") is not None
            else None
        ),
        "decisionReason": row.get("decision_reason") or "",
        "policyVersionId": _sid(row.get("policy_version_id")) or None,
        "decisionSessionId": _sid(row.get("decision_session_id")) or None,
        "finalizedAt": row.get("finalized_at").isoformat() if row.get("finalized_at") else None,
        "finalizedBy": _sid(row.get("finalized_by")) or None,
        "resultVersionNo": int(row.get("result_version_no") or 0),
        "status": row.get("status"),
    }
    return _canonical_hash(payload)


def _hr12_revision_hash(row: dict) -> str:
    payload = {
        "tenantId": int(row.get("tenant_id") or 0),
        "resultId": _sid(row.get("result_id")),
        "correctionNo": row.get("correction_no"),
        "previousVersion": int(row.get("previous_version") or 0),
        "newVersion": int(row.get("new_version") or 0),
        "revisionType": row.get("revision_type"),
        "reason": row.get("reason"),
        "authorityStaffId": _sid(row.get("authority_staff_id")) or None,
        "before": row.get("before_snapshot_json") or {},
        "after": row.get("after_snapshot_json") or {},
        "effectiveAt": row.get("effective_at").isoformat() if row.get("effective_at") else None,
    }
    return _canonical_hash(payload)


def _hr12_quality(*, tenant_id: int, rule_code: str, as_of_date=None):
    result_model = _model("hr_assessment", "HrFinalAssessmentResult")
    revision_model = _model("hr_assessment", "HrResultRevision")
    case_model = _model("hr_assessment", "HrAssessmentCase")
    if result_model is None or revision_model is None or case_model is None:
        return None

    results = result_model.objects.filter(tenant_id=tenant_id)
    revisions = revision_model.objects.filter(tenant_id=tenant_id)
    if as_of_date is not None:
        results = results.filter(finalized_at__date__lte=as_of_date)
        revisions = revisions.filter(effective_at__date__lte=as_of_date)

    result_rows = list(
        results.order_by("id").values(
            "id", "tenant_id", "case_id", "assessment_type", "cycle_id",
            "grade_code", "display_grade_snapshot_json", "calculated_score",
            "calculation_snapshot_json", "calculation_hash", "decision_reason",
            "policy_version_id", "decision_session_id", "finalized_at", "finalized_by",
            "result_version_no", "content_hash", "sealed_at", "status",
        )
    )
    result_ids = [row["id"] for row in result_rows]
    revision_rows = list(
        revisions.filter(result_id__in=result_ids)
        .order_by("result_id", "new_version", "effective_at", "id")
        .values(
            "id", "tenant_id", "result_id", "correction_no", "previous_version",
            "new_version", "revision_type", "reason", "authority_staff_id",
            "before_snapshot_json", "after_snapshot_json", "effective_at",
            "content_hash", "sealed_at",
        )
    )
    case_ids = [row["case_id"] for row in result_rows]
    case_rows = list(
        case_model.objects.filter(tenant_id=tenant_id, id__in=case_ids)
        .order_by("id")
        .values("id", "tenant_id", "staff_id", "assessment_type", "cycle_id")
    )
    case_map = {row["id"]: row for row in case_rows}
    revisions_by_result = defaultdict(list)
    for row in revision_rows:
        revisions_by_result[row["result_id"]].append(row)

    findings = []
    for result in result_rows:
        source_ref = f"assessment-result:{result['id']}"
        case = case_map.get(result["case_id"])
        if case is None:
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="ASSESSMENT_CASE_MISSING_OR_CROSS_TENANT", caseId=_sid(result["case_id"]),
            ))
        else:
            if not case.get("staff_id"):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="ASSESSMENT_STAFF_IDENTITY_MISSING",
                ))
            if case.get("assessment_type") != result.get("assessment_type"):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="ASSESSMENT_TYPE_LINEAGE_MISMATCH",
                ))
            if case.get("cycle_id") != result.get("cycle_id"):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=source_ref,
                    issue="ASSESSMENT_CYCLE_LINEAGE_MISMATCH",
                ))
        if not result.get("finalized_at") or not result.get("sealed_at"):
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="RESULT_SEAL_TIME_MISSING",
            ))
        if not _valid_hash(result.get("content_hash")) or result.get("content_hash") != _hr12_result_hash(result):
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="RESULT_CONTENT_HASH_INVALID",
            ))
        expected_calc = _canonical_hash(result.get("calculation_snapshot_json") or {})
        if not _valid_hash(result.get("calculation_hash")) or result.get("calculation_hash") != expected_calc:
            findings.append(_finding(
                rule_code=rule_code, source_ref=source_ref,
                issue="RESULT_CALCULATION_HASH_INVALID",
            ))

        state = _hr12_base_snapshot(result)
        version = int(result.get("result_version_no") or 0)
        last_effective_at = result.get("finalized_at")
        revoked = False
        for revision in revisions_by_result.get(result["id"], []):
            rev_ref = f"assessment-revision:{revision['id']}"
            if revoked:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_AFTER_REVOCATION",
                ))
            if (
                int(revision.get("previous_version") or 0) != version
                or int(revision.get("new_version") or 0) != version + 1
            ):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_VERSION_CHAIN_BROKEN", expectedPrevious=version,
                ))
            if revision.get("before_snapshot_json") != state:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_BEFORE_SNAPSHOT_MISMATCH",
                ))
            after = revision.get("after_snapshot_json") or {}
            if int(after.get("version") or 0) != int(revision.get("new_version") or 0):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_AFTER_VERSION_INVALID",
                ))
            revision_type = str(revision.get("revision_type") or "").upper()
            if revision_type == "CORRECTION" and after.get("status") != "CORRECTED":
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="CORRECTION_STATUS_INVALID",
                ))
            elif revision_type == "REVOCATION" and after.get("status") != "REVOKED":
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVOCATION_STATUS_INVALID",
                ))
            elif revision_type not in {"CORRECTION", "REVOCATION"}:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_TYPE_INVALID", revisionType=revision_type,
                ))
            if last_effective_at and revision.get("effective_at") and revision["effective_at"] < last_effective_at:
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_EFFECTIVE_TIME_NOT_MONOTONIC",
                ))
            if not _valid_hash(revision.get("content_hash")) or revision.get("content_hash") != _hr12_revision_hash(revision):
                findings.append(_finding(
                    rule_code=rule_code, source_ref=rev_ref,
                    issue="REVISION_CONTENT_HASH_INVALID",
                ))
            state = after
            version = int(revision.get("new_version") or version)
            last_effective_at = revision.get("effective_at") or last_effective_at
            revoked = after.get("status") == "REVOKED"

    evidence_rows = [
        {"kind": "result", **row} for row in result_rows
    ] + [
        {"kind": "revision", **row} for row in revision_rows
    ] + [
        {"kind": "caseIdentity", **row} for row in case_rows
    ]
    return findings, evidence_rows


def quality_provider(
    *,
    tenant_id: int,
    source_domain: str,
    rule_code: str,
    rule_version: int,
    rule_parameters,
    as_of_date=None,
    actor_user_id=None,
):
    del actor_user_id, rule_version
    try:
        tenant_id = int(tenant_id)
    except (TypeError, ValueError):
        return {"status": SourceStatus.ERROR.value}
    domain = str(source_domain or "").strip().upper()
    rule_code = str(rule_code or "").strip().upper()
    if tenant_id <= 0 or domain not in _SUPPORTED_RULES:
        return {"status": SourceStatus.ERROR.value}
    if rule_code not in _SUPPORTED_RULES[domain]:
        return {"status": SourceStatus.UNAVAILABLE.value}
    if rule_parameters not in (None, {}):
        return {"status": SourceStatus.ERROR.value}
    if as_of_date is not None and not isinstance(as_of_date, date):
        return {"status": SourceStatus.ERROR.value}

    if domain == "HR06":
        outcome = _hr06_quality(
            tenant_id=tenant_id, rule_code=rule_code, as_of_date=as_of_date
        )
    else:
        outcome = _hr12_quality(
            tenant_id=tenant_id, rule_code=rule_code, as_of_date=as_of_date
        )
    if outcome is None:
        return {"status": SourceStatus.UNAVAILABLE.value}
    findings, rows = outcome
    provider_version = _PROVIDER_VERSIONS[domain]
    return {
        "status": SourceStatus.OK.value,
        "providerVersion": provider_version,
        "evidenceHash": _evidence_hash(
            provider_version=provider_version,
            tenant_id=tenant_id,
            rule_code=rule_code,
            as_of_date=as_of_date,
            rows=rows,
        ),
        "findings": findings,
    }
