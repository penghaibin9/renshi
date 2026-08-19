"""Public read contract for finalized HR12 assessment evidence.

Consumers must use this boundary instead of trusting caller-provided snapshots or
querying HR12 tables with guessed identities. The contract resolves the
canonical HR03 person -> staff mapping inside one tenant and exposes only a
specific FINALIZED result that was effective by the requested as-of date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_staff.models import HrStaffMaster

PROVIDER_VERSION = "hr12-final-assessment-v1"


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
            "policyVersionId": (
                str(self.policy_version_id) if self.policy_version_id else None
            ),
            "decisionSessionId": (
                str(self.decision_session_id) if self.decision_session_id else None
            ),
        }


def get_finalized_assessment_evidence(
    *,
    tenant_id: int,
    person_id,
    result_id,
    as_of: date,
    source_version: str | None = None,
) -> FinalAssessmentEvidence:
    """Return one trusted HR12 final result for a canonical person.

    There is intentionally no "best effort" or legacy fallback. A mismatched
    tenant/person/result/version/as-of boundary is reported as unavailable.
    """

    if not tenant_id:
        raise AssessmentEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise AssessmentEvidenceUnavailable(
            "AS_OF_REQUIRED", "as_of must be a date"
        )
    if source_version and source_version != PROVIDER_VERSION:
        raise AssessmentEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR12 source version: {source_version}",
        )

    staff = (
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            person_id_id=person_id,
        )
        .order_by("id")
        .first()
    )
    if staff is None:
        raise AssessmentEvidenceUnavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "canonical HR03 staff mapping is unavailable for this person and tenant",
        )

    result = (
        HrFinalAssessmentResult.objects.filter(
            tenant_id=tenant_id,
            id=result_id,
            status="FINALIZED",
            finalized_at__isnull=False,
            finalized_at__date__lte=as_of,
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
        staff_id=staff.id,
    ).first()
    if case is None:
        raise AssessmentEvidenceUnavailable(
            "ASSESSMENT_RESULT_IDENTITY_MISMATCH",
            "requested HR12 result does not belong to the canonical person in this tenant",
        )

    return FinalAssessmentEvidence(
        result_id=result.id,
        case_id=case.id,
        staff_id=staff.id,
        assessment_type=result.assessment_type,
        grade_code=result.grade_code,
        display_grade=dict(result.display_grade_snapshot_json or {}),
        calculated_score=result.calculated_score,
        decision_reason=result.decision_reason,
        finalized_at=result.finalized_at,
        result_version_no=result.result_version_no,
        content_hash=result.content_hash,
        policy_version_id=result.policy_version_id,
        decision_session_id=result.decision_session_id,
    )
