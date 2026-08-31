"""Bounded cross-branch quality Providers for HR13 and HR14 formal facts.

These checks encode Authority invariants only.  They do not contain school policy
thresholds or mutate source data.  Sibling apps are resolved lazily through the
Django app registry: an isolated HR18 branch therefore returns UNAVAILABLE, while
an integrated tree can execute the same Provider against canonical formal facts.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from hr_data.services.source_gate import SourceStatus


_PROVIDER_VERSIONS = {
    "HR13": "hr13-title-quality-v1",
    "HR14": "hr14-appointment-quality-v1",
}
_SUPPORTED_RULES = {
    "HR13": {"HR13_RESULT_CHAIN_INTEGRITY"},
    "HR14": {"HR14_APPOINTMENT_FACT_INTEGRITY"},
}

_HR14_INITIAL_RECEIPT_KEYS = {
    "hr14PublicityId",
    "hr14QuotaReservationId",
    "hr03AssignmentId",
    "hr03RelationshipId",
    "hr02ReservationId",
    "hr02PositionId",
}
_HR14_TERMINAL_STATUSES = {"EFFECTIVE", "REVISED", "ENDED", "REVOKED"}


def _sid(value) -> str:
    return "" if value in (None, "") else str(value)


def _fingerprint(*, rule_code: str, source_ref: str, issue: str) -> str:
    raw = f"{rule_code}:{source_ref}:{issue}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finding(*, rule_code: str, source_ref: str, issue: str, **details):
    return {
        "sourceObjectRef": source_ref,
        "fingerprint": _fingerprint(
            rule_code=rule_code,
            source_ref=source_ref,
            issue=issue,
        ),
        "details": {"issue": issue, **details},
    }


def _hr13_findings(*, rule_code: str, rows: list[dict], cases: dict[str, str]):
    by_id = {_sid(row["id"]): row for row in rows}
    successors = defaultdict(list)
    findings = []

    for row in rows:
        row_id = _sid(row["id"])
        source_ref = f"title-result:{row_id}"
        predecessor_id = _sid(row.get("supersedes_result_id"))
        status = str(row.get("status") or "")

        if status in {"REVISED", "REVOKED"} and not predecessor_id:
            findings.append(
                _finding(
                    rule_code=rule_code,
                    source_ref=source_ref,
                    issue="SUCCESSOR_PREDECESSOR_REQUIRED",
                    status=status,
                )
            )
        if predecessor_id:
            successors[predecessor_id].append(row)
            if predecessor_id == row_id:
                findings.append(
                    _finding(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        issue="SELF_SUPERSEDES",
                    )
                )
            predecessor = by_id.get(predecessor_id)
            if predecessor is None:
                findings.append(
                    _finding(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        issue="PREDECESSOR_MISSING",
                        predecessorId=predecessor_id,
                    )
                )
            else:
                if _sid(predecessor.get("person_id")) != _sid(row.get("person_id")):
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="PREDECESSOR_PERSON_MISMATCH",
                            predecessorId=predecessor_id,
                        )
                    )
                if _sid(predecessor.get("application_case_id")) != _sid(
                    row.get("application_case_id")
                ):
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="PREDECESSOR_APPLICATION_MISMATCH",
                            predecessorId=predecessor_id,
                        )
                    )
                if row.get("effective_from") < predecessor.get("effective_from"):
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="SUCCESSOR_DATE_BEFORE_PREDECESSOR",
                            predecessorId=predecessor_id,
                        )
                    )

        case_id = _sid(row.get("application_case_id"))
        case_person = cases.get(case_id)
        if case_person is None:
            findings.append(
                _finding(
                    rule_code=rule_code,
                    source_ref=source_ref,
                    issue="APPLICATION_CASE_MISSING",
                    applicationCaseId=case_id,
                )
            )
        elif _sid(case_person) != _sid(row.get("person_id")):
            findings.append(
                _finding(
                    rule_code=rule_code,
                    source_ref=source_ref,
                    issue="APPLICATION_PERSON_MISMATCH",
                    applicationCaseId=case_id,
                )
            )

    for predecessor_id, child_rows in successors.items():
        if len(child_rows) <= 1:
            continue
        findings.append(
            _finding(
                rule_code=rule_code,
                source_ref=f"title-result:{predecessor_id}",
                issue="MULTIPLE_SUCCESSORS",
                successorIds=sorted(_sid(row["id"]) for row in child_rows),
            )
        )
    return findings


def _hr14_findings(*, rule_code: str, rows: list[dict]):
    by_id = {_sid(row["id"]): row for row in rows}
    successors = defaultdict(list)
    findings = []

    for row in rows:
        row_id = _sid(row["id"])
        source_ref = f"appointment-fact:{row_id}"
        predecessor_id = _sid(row.get("supersedes_fact_id"))
        status = str(row.get("status") or "")

        if predecessor_id:
            successors[predecessor_id].append(row)
            if predecessor_id == row_id:
                findings.append(
                    _finding(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        issue="SELF_SUPERSEDES",
                    )
                )
            predecessor = by_id.get(predecessor_id)
            if predecessor is None:
                findings.append(
                    _finding(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        issue="PREDECESSOR_MISSING",
                        predecessorId=predecessor_id,
                    )
                )
            else:
                if _sid(predecessor.get("person_id")) != _sid(row.get("person_id")):
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="PREDECESSOR_PERSON_MISMATCH",
                            predecessorId=predecessor_id,
                        )
                    )
                if _sid(predecessor.get("application_case_id")) != _sid(
                    row.get("application_case_id")
                ):
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="PREDECESSOR_APPLICATION_MISMATCH",
                            predecessorId=predecessor_id,
                        )
                    )
                if row.get("effective_from") <= predecessor.get("effective_from"):
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="SUCCESSOR_DATE_NOT_AFTER_PREDECESSOR",
                            predecessorId=predecessor_id,
                        )
                    )

        if status in _HR14_TERMINAL_STATUSES:
            receipt = row.get("effect_receipt_json")
            if not isinstance(receipt, dict) or not receipt:
                findings.append(
                    _finding(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        issue="EFFECT_RECEIPT_REQUIRED",
                        status=status,
                    )
                )
            elif predecessor_id:
                missing = [
                    key
                    for key in ("sourceFactId", "hr03AssignmentId", "hr03Effect")
                    if not receipt.get(key)
                ]
                if not receipt.get("hr14RenewalId") and not receipt.get("hr14ChangeId"):
                    missing.append("hr14RenewalId|hr14ChangeId")
                if receipt.get("sourceFactId") and str(receipt.get("sourceFactId")) != predecessor_id:
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="EFFECT_RECEIPT_SOURCE_MISMATCH",
                            predecessorId=predecessor_id,
                            receiptSourceFactId=str(receipt.get("sourceFactId")),
                        )
                    )
                if missing:
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="SUCCESSOR_EFFECT_RECEIPT_INCOMPLETE",
                            missingKeys=missing,
                        )
                    )
            elif status == "EFFECTIVE":
                missing = sorted(
                    key for key in _HR14_INITIAL_RECEIPT_KEYS if not receipt.get(key)
                )
                if missing:
                    findings.append(
                        _finding(
                            rule_code=rule_code,
                            source_ref=source_ref,
                            issue="INITIAL_EFFECT_RECEIPT_INCOMPLETE",
                            missingKeys=missing,
                        )
                    )

    for predecessor_id, child_rows in successors.items():
        terminal_children = [
            row for row in child_rows if str(row.get("status") or "") in _HR14_TERMINAL_STATUSES
        ]
        if len(terminal_children) <= 1:
            continue
        findings.append(
            _finding(
                rule_code=rule_code,
                source_ref=f"appointment-fact:{predecessor_id}",
                issue="MULTIPLE_TERMINAL_SUCCESSORS",
                successorIds=sorted(_sid(row["id"]) for row in terminal_children),
            )
        )
    return findings


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


def _model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


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
    """Execute a bounded HR13/HR14 invariant rule and return a typed receipt."""
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

    if domain == "HR13":
        fact_model = _model("hr_title", "ProfessionalTitleResult")
        case_model = _model("hr_title", "TitleApplicationCase")
        if fact_model is None or case_model is None:
            return {"status": SourceStatus.UNAVAILABLE.value}
        queryset = fact_model.objects.filter(tenant_id=tenant_id)
        if as_of_date is not None:
            queryset = queryset.filter(effective_from__lte=as_of_date)
        rows = list(
            queryset.order_by("id").values(
                "id",
                "person_id",
                "application_case_id",
                "status",
                "effective_from",
                "effective_to",
                "supersedes_result_id",
            )
        )
        case_ids = {_sid(row["application_case_id"]) for row in rows}
        cases = {
            _sid(row["id"]): _sid(row["person_id"])
            for row in case_model.objects.filter(
                tenant_id=tenant_id,
                id__in=case_ids,
            ).values("id", "person_id")
        }
        findings = _hr13_findings(rule_code=rule_code, rows=rows, cases=cases)
    else:
        fact_model = _model("hr_appointment", "PositionAppointmentFact")
        if fact_model is None:
            return {"status": SourceStatus.UNAVAILABLE.value}
        queryset = fact_model.objects.filter(tenant_id=tenant_id)
        if as_of_date is not None:
            queryset = queryset.filter(effective_from__lte=as_of_date)
        rows = list(
            queryset.order_by("id").values(
                "id",
                "person_id",
                "application_case_id",
                "status",
                "effective_from",
                "effective_to",
                "effect_receipt_json",
                "supersedes_fact_id",
            )
        )
        findings = _hr14_findings(rule_code=rule_code, rows=rows)

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
