"""Integrity quality gates for the Round6 HR04/HR05/HR15 Authority chains.

These providers deliberately validate the persisted authority payload rather than
mutable workflow projections. HR18 uses them both while freezing evidence and
while evaluating an as-of population, so corrupt or cross-tenant history fails
closed instead of producing a plausible but wrong number.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from hr_data.services.source_gate import SourceStatus

_PROVIDER_VERSIONS = {
    "HR04": "hr04-hiring-revision-chain-quality-v1",
    "HR05": "hr05-activation-amendment-chain-quality-v1",
    "HR15": "hr15-payroll-result-chain-quality-v1",
}
_SUPPORTED_RULES = {
    "HR04": {"HR04_HIRING_REVISION_CHAIN_INTEGRITY"},
    "HR05": {"HR05_ACTIVATION_AMENDMENT_CHAIN_INTEGRITY"},
    "HR15": {"HR15_PAYROLL_RESULT_CHAIN_INTEGRITY"},
}


def _model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _valid_hash(value) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _fingerprint(rule_code: str, source_ref: str, issue: str) -> str:
    return hashlib.sha256(f"{rule_code}:{source_ref}:{issue}".encode()).hexdigest()


def _finding(rule_code: str, source_ref: str, issue: str, **details):
    return {
        "sourceObjectRef": source_ref,
        "fingerprint": _fingerprint(rule_code, source_ref, issue),
        "details": {"issue": issue, **details},
    }


def _evidence_hash(*, provider_version, tenant_id, rule_code, as_of_date, rows):
    digest = hashlib.sha256()
    digest.update(json.dumps({
        "providerVersion": provider_version,
        "tenantId": tenant_id,
        "ruleCode": rule_code,
        "asOfDate": as_of_date.isoformat() if isinstance(as_of_date, date) else None,
    }, sort_keys=True, separators=(",", ":")).encode())
    digest.update(b"\n")
    for row in rows:
        digest.update(json.dumps(
            row, cls=DjangoJSONEncoder, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False,
        ).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _hr04_quality(*, tenant_id: int, rule_code: str, as_of_date=None):
    fact_model = _model("hr_recruitment", "HrHiringDecisionFact")
    revision_model = _model("hr_recruitment", "HrHiringDecisionRevision")
    if fact_model is None or revision_model is None:
        return None
    facts = fact_model.objects.filter(tenant_id=tenant_id)
    revisions = revision_model.objects.filter(tenant_id=tenant_id)
    if as_of_date is not None:
        facts = facts.filter(accepted_at__date__lte=as_of_date)
        revisions = revisions.filter(effective_at__date__lte=as_of_date)
    fact_rows = list(facts.order_by("id"))
    revision_rows = list(revisions.order_by("fact_id", "new_version", "effective_at", "id"))
    findings = []
    by_fact = defaultdict(list)
    fact_ids = {fact.id for fact in fact_rows}
    for revision in revision_rows:
        by_fact[revision.fact_id].append(revision)
        if revision.fact_id not in fact_ids:
            findings.append(
                _finding(
                    rule_code,
                    f"hiring-revision:{revision.id}",
                    "HIRING_REVISION_PARENT_MISSING_OR_FUTURE",
                )
            )

    for fact in fact_rows:
        ref = f"hiring-fact:{fact.id}"
        parents = (
            fact.offer.tenant_id,
            fact.proposed_hire.tenant_id,
            fact.application.tenant_id,
            fact.candidate.tenant_id,
            fact.recruitment_position.tenant_id,
        )
        if any(int(value) != tenant_id for value in parents):
            findings.append(_finding(rule_code, ref, "CROSS_TENANT_HIRING_LINEAGE"))
        if not fact.sealed_at or not _valid_hash(fact.content_hash) or fact.content_hash != fact.calculate_content_hash():
            findings.append(_finding(rule_code, ref, "HIRING_FACT_CONTENT_HASH_INVALID"))
        state = fact.canonical_payload()
        version = 1
        last_time = fact.accepted_at
        revoked = False
        for revision in by_fact.get(fact.id, []):
            rref = f"hiring-revision:{revision.id}"
            if int(revision.tenant_id) != tenant_id or revision.fact_id != fact.id:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_PARENT_INVALID"))
            if revoked:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_AFTER_REVOCATION"))
            if revision.previous_version != version or revision.new_version != version + 1:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_VERSION_CHAIN_BROKEN", expectedPrevious=version))
            if revision.before_snapshot_json != state:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_BEFORE_SNAPSHOT_MISMATCH"))
            if last_time and revision.effective_at and revision.effective_at < last_time:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_EFFECTIVE_TIME_NOT_MONOTONIC"))
            if not revision.sealed_at or not _valid_hash(revision.content_hash) or revision.content_hash != revision.calculate_content_hash():
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_CONTENT_HASH_INVALID"))
            after = revision.after_snapshot_json or {}
            action = str(revision.revision_type or "").upper()
            if action == "CORRECTION" and after.get("status") != "CORRECTED":
                findings.append(_finding(rule_code, rref, "HIRING_CORRECTION_STATUS_INVALID"))
            elif action == "REVOCATION" and after.get("status") != "REVOKED":
                findings.append(_finding(rule_code, rref, "HIRING_REVOCATION_STATUS_INVALID"))
            elif action not in {"CORRECTION", "REVOCATION"}:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_TYPE_INVALID"))
            if int(after.get("version") or 0) != revision.new_version:
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_AFTER_VERSION_INVALID"))
            identity_fields = {
                "tenantId", "offerId", "proposedHireId", "applicationId", "candidateId",
                "recruitmentPositionId", "offerNo", "acceptedAt", "approvedAt", "approvedBy",
            }
            if any(after.get(key) != state.get(key) for key in identity_fields):
                findings.append(_finding(rule_code, rref, "HIRING_REVISION_IDENTITY_CHANGED"))
            changed = {key for key in set(state) | set(after) if state.get(key) != after.get(key)} - {"status", "version"}
            if action == "CORRECTION" and (not changed or not changed.issubset({"rank", "finalScore", "employmentType", "expectedReportDate"})):
                findings.append(_finding(rule_code, rref, "HIRING_CORRECTION_PAYLOAD_INVALID"))
            if action == "REVOCATION" and changed:
                findings.append(_finding(rule_code, rref, "HIRING_REVOCATION_PAYLOAD_INVALID"))
            state = after
            version = revision.new_version
            last_time = revision.effective_at or last_time
            revoked = after.get("status") == "REVOKED"

    evidence = [
        {"kind": "hiringFact", "id": str(f.id), "acceptedAt": f.accepted_at, "contentHash": f.content_hash}
        for f in fact_rows
    ] + [
        {"kind": "hiringRevision", "id": str(r.id), "factId": str(r.fact_id), "newVersion": r.new_version,
         "effectiveAt": r.effective_at, "contentHash": r.content_hash}
        for r in revision_rows
    ]
    return findings, evidence


def _hr05_quality(*, tenant_id: int, rule_code: str, as_of_date=None):
    snapshot_model = _model("hr_onboarding", "HrOnboardingActivationSnapshot")
    amendment_model = _model("hr_onboarding", "HrOnboardingActivationAmendment")
    handoff_model = _model("hr_recruitment", "HrRecruitmentHandoff")
    hiring_model = _model("hr_recruitment", "HrHiringDecisionFact")
    hiring_revision_model = _model("hr_recruitment", "HrHiringDecisionRevision")
    if snapshot_model is None or amendment_model is None:
        return None
    snapshots = snapshot_model.objects.filter(tenant_id=tenant_id)
    amendments = amendment_model.objects.filter(tenant_id=tenant_id)
    if as_of_date is not None:
        snapshots = snapshots.filter(activated_at__date__lte=as_of_date)
        amendments = amendments.filter(effective_at__date__lte=as_of_date)
    snapshot_rows = list(snapshots.select_related("case").order_by("id"))
    amendment_rows = list(amendments.order_by("snapshot_id", "sequence_no", "effective_at", "id"))
    by_snapshot = defaultdict(list)
    findings = []
    snapshot_ids = {snapshot.id for snapshot in snapshot_rows}
    for amendment in amendment_rows:
        by_snapshot[amendment.snapshot_id].append(amendment)
        if amendment.snapshot_id not in snapshot_ids:
            findings.append(
                _finding(
                    rule_code,
                    f"activation-amendment:{amendment.id}",
                    "ACTIVATION_AMENDMENT_PARENT_MISSING_OR_FUTURE",
                )
            )

    for snapshot in snapshot_rows:
        ref = f"activation-snapshot:{snapshot.id}"
        case = snapshot.case
        if int(case.tenant_id) != tenant_id:
            findings.append(_finding(rule_code, ref, "CROSS_TENANT_ACTIVATION_CASE"))
        expected_parent = {
            "source_type": case.source_type or "",
            "source_id": case.source_id or "",
            "hr04_proposed_hire_id": case.hr04_proposed_hire_id or "",
            "hr04_application_id": case.hr04_application_id or "",
        }
        if any((getattr(snapshot, field) or "") != value for field, value in expected_parent.items()):
            findings.append(_finding(rule_code, ref, "ACTIVATION_PARENT_SNAPSHOT_MISMATCH"))
        hr03_links = (
            (snapshot.person_id, case.hr03_person_id),
            (snapshot.staff_master_id, case.hr03_staff_master_id),
            (snapshot.employment_id, case.hr03_employment_id),
            (snapshot.assignment_id, case.hr03_assignment_id),
        )
        if any(not left or not right or left != right for left, right in hr03_links):
            findings.append(_finding(rule_code, ref, "ACTIVATION_HR03_LINEAGE_MISMATCH"))
        if not snapshot.activated_at or not snapshot.sealed_at or not _valid_hash(snapshot.content_hash) or snapshot.content_hash != snapshot.calculate_content_hash():
            findings.append(_finding(rule_code, ref, "ACTIVATION_CONTENT_HASH_INVALID"))
        state = snapshot.canonical_payload()
        predecessor_id = None
        last_time = snapshot.activated_at
        revoked = False
        for sequence, amendment in enumerate(by_snapshot.get(snapshot.id, []), start=1):
            aref = f"activation-amendment:{amendment.id}"
            if int(amendment.tenant_id) != tenant_id or amendment.snapshot_id != snapshot.id:
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_PARENT_INVALID"))
            if amendment.sequence_no != sequence or amendment.predecessor_id != predecessor_id:
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_CHAIN_BROKEN", expectedSequence=sequence))
            if revoked:
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_AFTER_REVOCATION"))
            if amendment.before_snapshot_json != state:
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_BEFORE_SNAPSHOT_MISMATCH"))
            if last_time and amendment.effective_at and amendment.effective_at < last_time:
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_EFFECTIVE_TIME_NOT_MONOTONIC"))
            if not amendment.sealed_at or not _valid_hash(amendment.content_hash) or amendment.content_hash != amendment.calculate_content_hash():
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_CONTENT_HASH_INVALID"))
            action = str(amendment.action or "").upper()
            after = amendment.after_snapshot_json or {}
            if action not in {"CORRECTION", "REVOCATION"}:
                findings.append(_finding(rule_code, aref, "ACTIVATION_AMENDMENT_ACTION_INVALID"))
            if action == "REVOCATION" and not bool(after.get("revoked")):
                findings.append(_finding(rule_code, aref, "ACTIVATION_REVOCATION_STATE_INVALID"))
            allowed_correction = {"activatedAt", "staffNo", "organizationId", "positionId", "sourceVersions"}
            changed = {key for key in set(state) | set(after) if state.get(key) != after.get(key)}
            if action == "CORRECTION" and (not changed or not changed.issubset(allowed_correction)):
                findings.append(_finding(rule_code, aref, "ACTIVATION_CORRECTION_PAYLOAD_INVALID"))
            if action == "REVOCATION" and any(key not in {"revoked", "revocationReason"} for key in changed):
                findings.append(_finding(rule_code, aref, "ACTIVATION_REVOCATION_PAYLOAD_INVALID"))
            state = after
            predecessor_id = amendment.id
            last_time = amendment.effective_at or last_time
            revoked = action == "REVOCATION" or bool(after.get("revoked"))

        # Close the HR04 -> HR05 authority handoff for recruitment-origin cases.
        if str(snapshot.source_type or "") == "HR04_HIRE":
            if not snapshot.hr04_proposed_hire_id or not snapshot.hr04_application_id:
                findings.append(_finding(rule_code, ref, "HR04_HANDOFF_IDENTITY_REQUIRED"))
            elif handoff_model is None or hiring_model is None or hiring_revision_model is None:
                findings.append(_finding(rule_code, ref, "HR04_HANDOFF_SOURCE_UNAVAILABLE"))
            else:
                handoff = handoff_model.objects.filter(
                    tenant_id=tenant_id,
                    proposed_hire_id=snapshot.hr04_proposed_hire_id,
                    application_id=snapshot.hr04_application_id,
                    status="CREATED",
                ).first()
                if handoff is None or str(handoff.hr05_case_id or "") != str(case.id):
                    findings.append(_finding(rule_code, ref, "HR04_HR05_HANDOFF_MISMATCH"))
                hiring = hiring_model.objects.filter(
                    tenant_id=tenant_id,
                    proposed_hire_id=snapshot.hr04_proposed_hire_id,
                    application_id=snapshot.hr04_application_id,
                    accepted_at__lte=snapshot.activated_at,
                ).first()
                if hiring is None:
                    findings.append(_finding(rule_code, ref, "HR04_ACCEPTED_HIRE_FACT_REQUIRED"))
                else:
                    revoked_before_activation = hiring_revision_model.objects.filter(
                        tenant_id=tenant_id,
                        fact_id=hiring.id,
                        revision_type="REVOCATION",
                        effective_at__lte=snapshot.activated_at,
                    ).exists()
                    if revoked_before_activation:
                        findings.append(_finding(rule_code, ref, "HR04_HIRE_REVOKED_BEFORE_ACTIVATION"))

    evidence = [
        {"kind": "activationSnapshot", "id": str(s.id), "caseId": str(s.case_id),
         "activatedAt": s.activated_at, "contentHash": s.content_hash}
        for s in snapshot_rows
    ] + [
        {"kind": "activationAmendment", "id": str(a.id), "snapshotId": str(a.snapshot_id),
         "sequenceNo": a.sequence_no, "effectiveAt": a.effective_at, "contentHash": a.content_hash}
        for a in amendment_rows
    ]
    return findings, evidence


def _hr15_quality(*, tenant_id: int, rule_code: str, as_of_date=None):
    result_model = _model("hr_payroll", "PayrollResultFact")
    period_model = _model("hr_payroll", "PayrollPeriod")
    if result_model is None or period_model is None:
        return None
    results = result_model.objects.filter(tenant_id=tenant_id, status__in=("FINALIZED", "ADJUSTED", "REVERSED"))
    if as_of_date is not None:
        results = results.filter(effective_at__date__lte=as_of_date)
    rows = list(results.order_by("effective_at", "id"))
    period_ids = {row.payroll_period_id for row in rows}
    periods = {p.id: p for p in period_model.objects.filter(tenant_id=tenant_id, id__in=period_ids)}
    by_id = {row.id: row for row in rows}
    children = defaultdict(list)
    findings = []
    for row in rows:
        ref = f"payroll-result:{row.id}"
        if not row.effective_at or not row.sealed_at or not _valid_hash(row.content_hash) or row.content_hash != row.calculate_content_hash():
            findings.append(_finding(rule_code, ref, "PAYROLL_RESULT_CONTENT_HASH_INVALID"))
        try:
            if Decimal(row.net_amount) != Decimal(row.gross_amount) - Decimal(row.deduction_amount):
                findings.append(_finding(rule_code, ref, "PAYROLL_RESULT_ARITHMETIC_INVALID"))
        except Exception:
            findings.append(_finding(rule_code, ref, "PAYROLL_RESULT_ARITHMETIC_INVALID"))
        period = periods.get(row.payroll_period_id)
        if period is None:
            findings.append(_finding(rule_code, ref, "PAYROLL_PERIOD_MISSING_OR_CROSS_TENANT"))
        elif row.status == "FINALIZED" and (not period.finalized_at or period.finalized_at > row.effective_at):
            findings.append(_finding(rule_code, ref, "PAYROLL_FINALIZATION_TIME_INVALID"))
        if row.status == "FINALIZED" and row.supersedes_result_id:
            findings.append(_finding(rule_code, ref, "PAYROLL_FINALIZED_HAS_PREDECESSOR"))
        if row.status in {"ADJUSTED", "REVERSED"}:
            if not (row.authority_reason or "").strip():
                findings.append(_finding(rule_code, ref, "PAYROLL_DERIVED_REASON_REQUIRED"))
            if not row.supersedes_result_id:
                findings.append(_finding(rule_code, ref, "PAYROLL_DERIVED_PREDECESSOR_REQUIRED"))
            else:
                children[row.supersedes_result_id].append(row)
                parent = by_id.get(row.supersedes_result_id)
                if parent is None:
                    findings.append(_finding(rule_code, ref, "PAYROLL_PREDECESSOR_MISSING_OR_FUTURE"))
                else:
                    if (
                        parent.payroll_period_id != row.payroll_period_id
                        or parent.staff_id != row.staff_id
                        or parent.currency_code != row.currency_code
                    ):
                        findings.append(_finding(rule_code, ref, "PAYROLL_PREDECESSOR_IDENTITY_MISMATCH"))
                    if parent.effective_at and row.effective_at and row.effective_at < parent.effective_at:
                        findings.append(_finding(rule_code, ref, "PAYROLL_EFFECTIVE_TIME_NOT_MONOTONIC"))
                    if parent.status == "REVERSED":
                        findings.append(_finding(rule_code, ref, "PAYROLL_SUCCESSOR_AFTER_REVERSAL"))
    for parent_id, successors in children.items():
        if len(successors) > 1:
            findings.append(_finding(rule_code, f"payroll-result:{parent_id}", "PAYROLL_RESULT_BRANCH_CONFLICT", successorCount=len(successors)))

    # Every chain visible as of this date must terminate in one FINALIZED root.
    for row in rows:
        seen = set()
        current = row
        chain = []
        while current is not None:
            if current.id in seen:
                findings.append(_finding(rule_code, f"payroll-result:{row.id}", "PAYROLL_RESULT_CYCLE"))
                current = None
                break
            seen.add(current.id)
            chain.append(current)
            if not current.supersedes_result_id:
                break
            current = by_id.get(current.supersedes_result_id)
        if current is not None and not current.supersedes_result_id and current.status != "FINALIZED":
            findings.append(_finding(rule_code, f"payroll-result:{row.id}", "PAYROLL_CHAIN_ROOT_NOT_FINALIZED"))
        if row.status == "REVERSED" and len(chain) >= 2:
            predecessors = chain[1:]
            if any(item.status == "REVERSED" for item in predecessors):
                findings.append(_finding(rule_code, f"payroll-result:{row.id}", "PAYROLL_SUCCESSOR_AFTER_REVERSAL"))
            expected_gross = -sum((Decimal(item.gross_amount) for item in predecessors), Decimal("0"))
            expected_deduction = -sum((Decimal(item.deduction_amount) for item in predecessors), Decimal("0"))
            expected_net = -sum((Decimal(item.net_amount) for item in predecessors), Decimal("0"))
            if (
                Decimal(row.gross_amount) != expected_gross
                or Decimal(row.deduction_amount) != expected_deduction
                or Decimal(row.net_amount) != expected_net
            ):
                findings.append(_finding(rule_code, f"payroll-result:{row.id}", "PAYROLL_REVERSAL_AMOUNT_MISMATCH"))

    evidence = [
        {"kind": "payrollResult", "id": str(r.id), "periodId": str(r.payroll_period_id),
         "staffId": str(r.staff_id), "status": r.status, "supersedesResultId": str(r.supersedes_result_id or ""),
         "effectiveAt": r.effective_at, "contentHash": r.content_hash}
        for r in rows
    ] + [
        {"kind": "payrollPeriod", "id": str(p.id), "periodCode": p.period_code,
         "startDate": p.start_date, "endDate": p.end_date, "finalizedAt": p.finalized_at,
         "timeSource": p.time_source_snapshot_json}
        for p in sorted(periods.values(), key=lambda value: str(value.id))
    ]
    return findings, evidence


def quality_provider(*, tenant_id: int, source_domain: str, rule_code: str, rule_version: int,
                     rule_parameters, as_of_date=None, actor_user_id=None):
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
    try:
        if domain == "HR04":
            outcome = _hr04_quality(tenant_id=tenant_id, rule_code=rule_code, as_of_date=as_of_date)
        elif domain == "HR05":
            outcome = _hr05_quality(tenant_id=tenant_id, rule_code=rule_code, as_of_date=as_of_date)
        else:
            outcome = _hr15_quality(tenant_id=tenant_id, rule_code=rule_code, as_of_date=as_of_date)
    except Exception:
        return {"status": SourceStatus.ERROR.value}
    if outcome is None:
        return {"status": SourceStatus.UNAVAILABLE.value}
    findings, rows = outcome
    provider_version = _PROVIDER_VERSIONS[domain]
    return {
        "status": SourceStatus.OK.value,
        "providerVersion": provider_version,
        "evidenceHash": _evidence_hash(
            provider_version=provider_version, tenant_id=tenant_id,
            rule_code=rule_code, as_of_date=as_of_date, rows=rows,
        ),
        "findings": findings,
    }
