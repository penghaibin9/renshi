"""Public read contracts for finalized HR12 assessment evidence.

Consumers must use this boundary instead of trusting caller-provided snapshots or
querying HR12 tables with guessed identities. The contract resolves canonical
HR03 identity inside one tenant and exposes only FINALIZED results effective by
the requested as-of date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from django.db.models import Prefetch

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import (
    HrFinalAssessmentResult,
    HrResultApplicationLedger,
    HrResultRevision,
)
from hr_staff.models import HrStaffMaster

PROVIDER_VERSION = "hr12-final-assessment-v2"


class AssessmentEvidenceUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class FinalAssessmentEvidence:
    result_id: UUID
    case_id: UUID
    staff_id: UUID
    assessment_type: str
    grade_code: str
    display_grade: dict
    calculated_score: Optional[Decimal]
    decision_reason: str
    finalized_at: datetime
    result_version_no: int
    content_hash: str
    policy_version_id: Optional[UUID]
    decision_session_id: Optional[UUID]
    source_result_content_hash: str
    calculation_hash: str
    revision_id: Optional[UUID] = None
    revision_type: str = ""
    source_version: str = PROVIDER_VERSION

    def snapshot(self) -> dict:
        return {
            "assessmentResultId": str(self.result_id),
            "assessmentCaseId": str(self.case_id),
            "staffId": str(self.staff_id),
            "assessmentType": self.assessment_type,
            "gradeCode": self.grade_code,
            "displayGrade": dict(self.display_grade or {}),
            "calculatedScore": (
                str(self.calculated_score) if self.calculated_score is not None else None
            ),
            "decisionReason": self.decision_reason,
            "finalizedAt": self.finalized_at.isoformat(),
            "resultVersionNo": self.result_version_no,
            "contentHash": self.content_hash,
            "sourceResultContentHash": self.source_result_content_hash,
            "calculationHash": self.calculation_hash,
            "revisionId": str(self.revision_id) if self.revision_id else None,
            "revisionType": self.revision_type or None,
            "policyVersionId": (
                str(self.policy_version_id) if self.policy_version_id else None
            ),
            "decisionSessionId": (
                str(self.decision_session_id) if self.decision_session_id else None
            ),
        }


def _validate_request(*, tenant_id: int, as_of: date, source_version: str | None) -> None:
    if not tenant_id:
        raise AssessmentEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise AssessmentEvidenceUnavailable(
            "AS_OF_REQUIRED", "as_of must be a date"
        )
    if source_version and source_version != PROVIDER_VERSION:
        raise AssessmentEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR12 source version: {source_version}",
        )


def _canonical_staff(*, tenant_id: int, person_id, staff_id=None) -> HrStaffMaster:
    qs = HrStaffMaster.objects.filter(
        tenant_id=tenant_id,
        person_id_id=person_id,
    )
    if staff_id is not None:
        qs = qs.filter(id=staff_id)
    matches = list(qs.order_by("id")[:2])
    staff = matches[0] if len(matches) == 1 else None
    if staff is None:
        code = (
            "SOURCE_IDENTITY_MAPPING_AMBIGUOUS"
            if len(matches) > 1
            else "SOURCE_IDENTITY_MAPPING_UNAVAILABLE"
        )
        raise AssessmentEvidenceUnavailable(
            code,
            "canonical HR03 staff mapping is unavailable for this person and tenant",
        )
    return staff


def _to_evidence(
    result: HrFinalAssessmentResult,
    staff_id,
    revision: HrResultRevision | None = None,
) -> FinalAssessmentEvidence:
    if result.content_hash != result.calculate_content_hash():
        raise AssessmentEvidenceUnavailable(
            "FINAL_ASSESSMENT_RESULT_INTEGRITY_FAILED",
            "formal HR12 result content hash does not match its sealed content",
        )
    if result.calculation_hash != result.calculate_calculation_hash():
        raise AssessmentEvidenceUnavailable(
            "FINAL_ASSESSMENT_CALCULATION_INTEGRITY_FAILED",
            "formal HR12 calculation snapshot hash does not match its sealed content",
        )
    current = HrResultRevision._base_snapshot(result)
    content_hash = result.content_hash
    revision_id = None
    revision_type = ""
    if revision is not None:
        revisions = getattr(result, "effective_revisions", None)
        if revisions is None:
            revisions = list(
                result.revisions.filter(new_version__lte=revision.new_version).order_by(
                    "new_version", "effective_at", "id"
                )
            )
        else:
            revisions = sorted(
                revisions,
                key=lambda item: (item.new_version, item.effective_at, str(item.id)),
            )
        expected_version = int(result.result_version_no)
        for chain_item in revisions:
            if (
                int(chain_item.tenant_id) != int(result.tenant_id)
                or chain_item.result_id != result.id
                or int(chain_item.previous_version) != expected_version
                or int(chain_item.new_version) != expected_version + 1
                or (chain_item.before_snapshot_json or {}) != current
                or int((chain_item.after_snapshot_json or {}).get("version") or 0)
                != int(chain_item.new_version)
                or chain_item.content_hash != chain_item.calculate_content_hash()
            ):
                raise AssessmentEvidenceUnavailable(
                    "FINAL_ASSESSMENT_REVISION_INTEGRITY_FAILED",
                    "formal HR12 result revision chain is not contiguous and sealed",
                )
            current = chain_item.after_snapshot_json or {}
            content_hash = chain_item.content_hash
            revision_id = chain_item.id
            revision_type = chain_item.revision_type
            expected_version = int(chain_item.new_version)
    raw_score = current.get("calculatedScore")
    return FinalAssessmentEvidence(
        result_id=result.id,
        case_id=result.case_id,
        staff_id=staff_id,
        assessment_type=result.assessment_type,
        grade_code=str(current.get("gradeCode") or ""),
        display_grade=dict(current.get("displayGrade") or {}),
        calculated_score=Decimal(str(raw_score)) if raw_score is not None else None,
        decision_reason=str(current.get("decisionReason") or ""),
        finalized_at=result.finalized_at,
        result_version_no=int(current.get("version") or result.result_version_no),
        content_hash=content_hash,
        policy_version_id=result.policy_version_id,
        decision_session_id=result.decision_session_id,
        source_result_content_hash=result.content_hash,
        calculation_hash=result.calculation_hash,
        revision_id=revision_id,
        revision_type=revision_type,
    )


def _latest_effective_revision(result: HrFinalAssessmentResult) -> HrResultRevision | None:
    prefetched = getattr(result, "effective_revisions", None)
    if prefetched is not None:
        return prefetched[0] if prefetched else None
    return result.revisions.order_by("-new_version", "-effective_at", "-id").first()


def record_result_application(
    *,
    tenant_id: int,
    evidence: FinalAssessmentEvidence,
    consumer_domain: str,
    consumer_object_id,
    purpose: str,
) -> HrResultApplicationLedger:
    """Append one idempotent downstream-use fact for a trusted public result."""

    if not tenant_id:
        raise AssessmentEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    domain = str(consumer_domain or "").strip().upper()
    purpose_code = str(purpose or "").strip().upper()
    if not domain or not purpose_code or consumer_object_id is None:
        raise AssessmentEvidenceUnavailable(
            "ASSESSMENT_RESULT_APPLICATION_INVALID",
            "consumer domain, object identity and purpose are required",
        )
    result = HrFinalAssessmentResult.objects.filter(
        tenant_id=tenant_id,
        id=evidence.result_id,
    ).first()
    if result is None:
        raise AssessmentEvidenceUnavailable(
            "FINAL_ASSESSMENT_RESULT_UNAVAILABLE",
            "formal HR12 result is unavailable inside tenant",
        )
    if (
        evidence.source_version != PROVIDER_VERSION
        or evidence.case_id != result.case_id
        or evidence.source_result_content_hash != result.content_hash
        or evidence.calculation_hash != result.calculation_hash
    ):
        raise AssessmentEvidenceUnavailable(
            "ASSESSMENT_RESULT_APPLICATION_EVIDENCE_MISMATCH",
            "consumer evidence does not match the sealed HR12 source result",
        )
    revision = None
    if int(evidence.result_version_no) != int(result.result_version_no):
        revision = HrResultRevision.objects.filter(
            tenant_id=tenant_id,
            result=result,
            new_version=evidence.result_version_no,
            content_hash=evidence.content_hash,
            id=evidence.revision_id,
            revision_type=evidence.revision_type,
        ).exclude(after_snapshot_json__status="REVOKED").first()
        version_matches = revision is not None
    else:
        version_matches = (
            evidence.content_hash == result.content_hash
            and evidence.revision_id is None
            and not evidence.revision_type
        )
    if not version_matches or _to_evidence(result, evidence.staff_id, revision) != evidence:
        raise AssessmentEvidenceUnavailable(
            "ASSESSMENT_RESULT_APPLICATION_VERSION_MISMATCH",
            "consumer evidence version is not an effective sealed HR12 result",
        )
    ledger, _created = HrResultApplicationLedger.objects.get_or_create(
        tenant_id=tenant_id,
        result=result,
        consumer_domain=domain,
        consumer_object_id=consumer_object_id,
        purpose=purpose_code,
        result_version=evidence.result_version_no,
        defaults={"consumer_status": "CONSUMED"},
    )
    return ledger


def list_finalized_assessment_evidence(
    *,
    tenant_id: int,
    person_id,
    staff_id,
    as_of: date,
    source_version: str | None = None,
) -> tuple[FinalAssessmentEvidence, ...]:
    """Return all trusted FINALIZED HR12 results for one canonical HR03 staff.

    Empty results are a complete source answer. Identity/version/as-of mismatch
    is unavailable rather than a fake empty success.
    """
    _validate_request(
        tenant_id=tenant_id,
        as_of=as_of,
        source_version=source_version,
    )
    staff = _canonical_staff(
        tenant_id=tenant_id,
        person_id=person_id,
        staff_id=staff_id,
    )
    case_ids = HrAssessmentCase.objects.filter(
        tenant_id=tenant_id,
        staff_id=staff.id,
    ).values_list("id", flat=True)
    results = HrFinalAssessmentResult.objects.filter(
        tenant_id=tenant_id,
        case_id__in=case_ids,
        status="FINALIZED",
        finalized_at__isnull=False,
        finalized_at__date__lte=as_of,
    ).prefetch_related(
        Prefetch(
            "revisions",
            queryset=HrResultRevision.objects.filter(
                tenant_id=tenant_id,
                effective_at__isnull=False,
                effective_at__date__lte=as_of,
            ).order_by("-new_version", "-effective_at", "-id"),
            to_attr="effective_revisions",
        )
    ).order_by("finalized_at", "id")
    evidence = []
    for result in results:
        revision = _latest_effective_revision(result)
        if revision is not None and (revision.after_snapshot_json or {}).get("status") == "REVOKED":
            continue
        evidence.append(_to_evidence(result, staff.id, revision))
    return tuple(evidence)


def get_finalized_assessment_evidence(
    *,
    tenant_id: int,
    person_id,
    result_id,
    as_of: date,
    source_version: str | None = None,
) -> FinalAssessmentEvidence:
    """Return one trusted HR12 final result for a canonical person."""
    _validate_request(
        tenant_id=tenant_id,
        as_of=as_of,
        source_version=source_version,
    )
    result = (
        HrFinalAssessmentResult.objects.filter(
            tenant_id=tenant_id,
            id=result_id,
            status="FINALIZED",
            finalized_at__isnull=False,
            finalized_at__date__lte=as_of,
        )
        .prefetch_related(
            Prefetch(
                "revisions",
                queryset=HrResultRevision.objects.filter(
                    tenant_id=tenant_id,
                    effective_at__isnull=False,
                    effective_at__date__lte=as_of,
                ).order_by("-new_version", "-effective_at", "-id"),
                to_attr="effective_revisions",
            )
        )
        .first()
    )
    if result is None:
        raise AssessmentEvidenceUnavailable(
            "FINAL_ASSESSMENT_RESULT_UNAVAILABLE",
            "requested HR12 result is not FINALIZED and effective in this tenant/as-of boundary",
        )

    case = HrAssessmentCase.objects.filter(
        tenant_id=tenant_id,
        id=result.case_id,
    ).first()
    if case is None:
        raise AssessmentEvidenceUnavailable(
            "ASSESSMENT_RESULT_IDENTITY_MISMATCH",
            "requested HR12 result does not belong to the canonical person in this tenant",
        )
    try:
        staff = _canonical_staff(
            tenant_id=tenant_id,
            person_id=person_id,
            staff_id=case.staff_id,
        )
    except AssessmentEvidenceUnavailable as exc:
        if exc.code == "SOURCE_IDENTITY_MAPPING_UNAVAILABLE":
            raise AssessmentEvidenceUnavailable(
                "ASSESSMENT_RESULT_IDENTITY_MISMATCH",
                "requested HR12 result does not belong to the canonical person in this tenant",
            ) from exc
        raise
    revision = _latest_effective_revision(result)
    if revision is not None and (revision.after_snapshot_json or {}).get("status") == "REVOKED":
        raise AssessmentEvidenceUnavailable(
            "FINAL_ASSESSMENT_RESULT_REVOKED",
            "requested HR12 result was revoked by an effective formal revision",
        )
    return _to_evidence(result, staff.id, revision)
