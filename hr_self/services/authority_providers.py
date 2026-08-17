"""SELF-safe read adapters for HR17 strong source Authorities.

These adapters deliberately expose only staff-owned read models. They never
recompute source-domain truth, mutate a source state machine, or pass through
raw documents / internal approval payloads.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from hr_self.services.identity_service import SelfIdentityContext


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _identifier(value) -> Optional[str]:
    return str(value) if value is not None else None


def _amount(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _latest_source_updated_at(*groups) -> Optional[datetime]:
    timestamps = [
        getattr(row, "updated_at", None)
        for group in groups
        for row in group
        if getattr(row, "updated_at", None) is not None
    ]
    return max(timestamps, default=None)


def _ok(data, *, source_updated_at=None, provider_version: str, authority: str):
    # Lazy import avoids a module cycle: provider_gateway owns the result envelope
    # and imports this module only while building the default registry.
    from hr_self.services.provider_gateway import SelfProviderResult

    return SelfProviderResult.ok(
        data,
        source_updated_at=source_updated_at,
        provider_version=provider_version,
        meta={"scope": "SELF", "authority": authority},
    )


def hr09_self_provider(context: SelfIdentityContext):
    """Read HR09 credential facts without exposing certificate ciphertext/hash."""

    from hr_qualification.models.credential import HrPersonCredential

    credentials = list(
        HrPersonCredential.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-updated_at")[:50]
    )
    data = {
        "credentials": [
            {
                "id": _identifier(row.id),
                "name": row.credential_name_snapshot,
                "levelCode": row.level_code,
                "maskedCertificateNo": row.masked_no,
                "issuerName": row.issuer_name,
                "issueDate": _iso(row.issue_date),
                "validFrom": _iso(row.valid_from),
                "validTo": _iso(row.valid_to),
                "status": row.status,
                "verificationStatus": row.current_verification_status,
                "lastVerifiedAt": _iso(row.last_verified_at),
                "selfReported": bool(row.self_reported),
                "updatedAt": _iso(row.updated_at),
            }
            for row in credentials
        ]
    }
    return _ok(
        data,
        source_updated_at=_latest_source_updated_at(credentials),
        provider_version="hr09.credential-authority-self.1",
        authority="HR09_QUALIFICATION_AUTHORITY",
    )


def hr10_self_provider(context: SelfIdentityContext):
    """Read immutable HR10 development facts through the resolved legacy mapping.

    HR10's current Authority table still stores ``staff_master_id`` as a
    BigInteger. HR17 identity is UUID-first, therefore lack of a resolved legacy
    employee mapping is an integration-unavailable condition, not an empty
    development record.
    """

    from hr_self.services.provider_gateway import SelfProviderResult

    if context.legacy_employee_id is None:
        return SelfProviderResult.unavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "HR10 requires a resolved legacy employee mapping for staff_master_id",
            provider_version="hr10.development-authority-self.1",
        )

    from hr10_development.models.development_fact import HrDevelopmentFact

    facts = list(
        HrDevelopmentFact.objects.filter(
            tenant_id=context.tenant_id,
            staff_master_id=context.legacy_employee_id,
        ).order_by("-valid_from", "-generated_at")[:100]
    )
    data = {
        "developmentFacts": [
            {
                "id": _identifier(row.id),
                "factType": row.fact_type,
                "activityType": row.activity_type,
                "startDate": _iso(row.start_date),
                "endDate": _iso(row.end_date),
                "verifiedHours": _amount(row.verified_hours),
                "verifiedDays": row.verified_days,
                "verifiedCredits": _amount(row.verified_credits),
                "levelOrResult": row.level_or_result,
                "verificationStatus": row.verification_status,
                "generatedAt": _iso(row.generated_at),
                "validFrom": _iso(row.valid_from),
                "validTo": _iso(row.valid_to),
                "supersedesFactId": _identifier(row.supersedes_fact_id),
                "updatedAt": _iso(row.updated_at),
            }
            for row in facts
        ]
    }
    return _ok(
        data,
        source_updated_at=_latest_source_updated_at(facts),
        provider_version="hr10.development-authority-self.1",
        authority="HR10_DEVELOPMENT_AUTHORITY",
    )


def hr12_self_provider(context: SelfIdentityContext):
    """Read own assessment case progress and immutable finalized result facts."""

    from hr_assessment.models.case import HrAssessmentCase
    from hr_assessment.models.result import HrFinalAssessmentResult

    cases = list(
        HrAssessmentCase.objects.filter(
            tenant_id=context.tenant_id,
            staff_id=context.staff_id,
        ).order_by("-updated_at")[:50]
    )
    case_ids = [row.id for row in cases]
    results = list(
        HrFinalAssessmentResult.objects.filter(
            tenant_id=context.tenant_id,
            case_id__in=case_ids,
        ).order_by("-finalized_at", "-created_at")[:50]
    )
    data = {
        "assessmentCases": [
            {
                "id": _identifier(row.id),
                "assessmentType": row.assessment_type,
                "cycleId": _identifier(row.cycle_id),
                "policyVersionId": _identifier(row.policy_version_id),
                "status": row.status,
                "updatedAt": _iso(row.updated_at),
            }
            for row in cases
        ],
        "finalResults": [
            {
                "id": _identifier(row.id),
                "caseId": _identifier(row.case_id),
                "assessmentType": row.assessment_type,
                "cycleId": _identifier(row.cycle_id),
                "gradeCode": row.grade_code,
                "calculatedScore": _amount(row.calculated_score),
                "status": row.status,
                "resultVersionNo": row.result_version_no,
                "finalizedAt": _iso(row.finalized_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in results
        ],
    }
    return _ok(
        data,
        source_updated_at=_latest_source_updated_at(cases, results),
        provider_version="hr12.assessment-authority-self.1",
        authority="HR12_ASSESSMENT_AUTHORITY",
    )


def hr13_self_provider(context: SelfIdentityContext):
    """Read own professional-title application progress and formal result facts."""

    from hr_title.models import ProfessionalTitleResult, TitleApplicationCase

    applications = list(
        TitleApplicationCase.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-updated_at")[:50]
    )
    results = list(
        ProfessionalTitleResult.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-effective_from", "-created_at")[:50]
    )
    data = {
        "titleApplications": [
            {
                "id": _identifier(row.id),
                "caseNo": row.case_no,
                "batchNo": row.batch_no,
                "requestedTitleCode": row.requested_title_code,
                "requestedTitleName": row.requested_title_name,
                "status": row.status,
                "submittedAt": _iso(row.submitted_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in applications
        ],
        "professionalTitleResults": [
            {
                "id": _identifier(row.id),
                "resultNo": row.result_no,
                "applicationCaseId": _identifier(row.application_case_id),
                "titleCode": row.title_code,
                "titleName": row.title_name,
                "titleSeriesCode": row.title_series_code,
                "titleLevelCode": row.title_level_code,
                "effectiveFrom": _iso(row.effective_from),
                "effectiveTo": _iso(row.effective_to),
                "status": row.status,
                "supersedesResultId": _identifier(row.supersedes_result_id),
                "updatedAt": _iso(row.updated_at),
            }
            for row in results
        ],
    }
    return _ok(
        data,
        source_updated_at=_latest_source_updated_at(applications, results),
        provider_version="hr13.title-authority-self.1",
        authority="HR13_TITLE_AUTHORITY",
    )


def hr15_self_provider(context: SelfIdentityContext):
    """Read own HR15 payroll profile metadata and finalized payroll facts.

    Bank/payment-account references and payroll identity numbers stay inside HR15.
    The adapter does not calculate payroll; it only projects source result facts.
    """

    from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact

    profiles = list(
        PayrollProfile.objects.filter(
            tenant_id=context.tenant_id,
            staff_id=context.staff_id,
        ).order_by("-effective_from", "-created_at")[:20]
    )
    results = list(
        PayrollResultFact.objects.filter(
            tenant_id=context.tenant_id,
            staff_id=context.staff_id,
        ).order_by("-created_at")[:50]
    )
    period_ids = {row.payroll_period_id for row in results}
    periods = list(
        PayrollPeriod.objects.filter(
            tenant_id=context.tenant_id,
            id__in=period_ids,
        ).order_by("-end_date", "-created_at")
    ) if period_ids else []
    periods_by_id = {row.id: row for row in periods}

    data = {
        "payrollProfiles": [
            {
                "id": _identifier(row.id),
                "payGroupCode": row.pay_group_code,
                "currencyCode": row.currency_code,
                "effectiveFrom": _iso(row.effective_from),
                "effectiveTo": _iso(row.effective_to),
                "status": row.status,
                "updatedAt": _iso(row.updated_at),
            }
            for row in profiles
        ],
        "payrollResults": [
            {
                "id": _identifier(row.id),
                "resultNo": row.result_no,
                "payrollPeriodId": _identifier(row.payroll_period_id),
                "periodCode": getattr(periods_by_id.get(row.payroll_period_id), "period_code", None),
                "currencyCode": row.currency_code,
                "grossAmount": _amount(row.gross_amount),
                "deductionAmount": _amount(row.deduction_amount),
                "netAmount": _amount(row.net_amount),
                "status": row.status,
                "supersedesResultId": _identifier(row.supersedes_result_id),
                "createdAt": _iso(row.created_at),
                "updatedAt": _iso(row.updated_at),
            }
            for row in results
        ],
    }
    return _ok(
        data,
        source_updated_at=_latest_source_updated_at(profiles, results, periods),
        provider_version="hr15.payroll-authority-self.1",
        authority="HR15_PAYROLL_AUTHORITY",
    )
