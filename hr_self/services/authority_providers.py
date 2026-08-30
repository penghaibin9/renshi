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


def hr04_self_provider(context: SelfIdentityContext):
    """Read the recruitment trail linked to this canonical HR03 staff record.

    HR04 intentionally has no mutable staff FK because a candidate predates an
    employee.  The immutable HR04→HR05 handoff and HR05→HR03 activation links
    provide the safe mapping; email, phone, identity ciphertext and application
    form snapshots are never exposed here.
    """

    from hr_onboarding.models import HrOnboardingCase
    from hr_recruitment.models import (
        HrJobApplication,
        HrProposedHire,
        HrRecruitmentOffer,
    )

    links = list(
        HrOnboardingCase.objects.filter(
            tenant_id=context.tenant_id,
            hr03_staff_master_id=context.staff_id,
        ).order_by("-updated_at")[:20]
    )
    application_ids = {
        str(row.hr04_application_id)
        for row in links
        if row.hr04_application_id
    }
    proposed_hire_ids = {
        str(row.hr04_proposed_hire_id)
        for row in links
        if row.hr04_proposed_hire_id
    }
    applications = list(
        HrJobApplication.objects.filter(
            tenant_id=context.tenant_id,
            id__in=application_ids,
        ).order_by("-updated_at")[:20]
    ) if application_ids else []
    proposed_hires = list(
        HrProposedHire.objects.filter(
            tenant_id=context.tenant_id,
            id__in=proposed_hire_ids,
        ).order_by("-updated_at")[:20]
    ) if proposed_hire_ids else []
    offers = list(
        HrRecruitmentOffer.objects.filter(
            tenant_id=context.tenant_id,
            proposed_hire_id__in=proposed_hire_ids,
        ).order_by("-updated_at")[:20]
    ) if proposed_hire_ids else []

    return _ok(
        {
            "applications": [
                {
                    "id": _identifier(row.id),
                    "applicationNo": row.application_no,
                    "status": row.canonical_status,
                    "workflowStageName": row.workflow_stage_name,
                    "submittedAt": _iso(row.submitted_at),
                    "finalDecisionAt": _iso(row.final_decision_at),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in applications
            ],
            "proposedHires": [
                {
                    "id": _identifier(row.id),
                    "applicationId": _identifier(row.application_id_id),
                    "decision": row.decision,
                    "approvalStatus": row.approval_status,
                    "approvedAt": _iso(row.approved_at),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in proposed_hires
            ],
            "offers": [
                {
                    "id": _identifier(row.id),
                    "offerNo": row.offer_no,
                    "proposedHireId": _identifier(row.proposed_hire_id_id),
                    "status": row.status,
                    "issuedAt": _iso(row.issued_at),
                    "expiresAt": _iso(row.expires_at),
                    "acceptedAt": _iso(row.accepted_at),
                    "expectedReportDate": _iso(row.expected_report_date),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in offers
            ],
        },
        source_updated_at=_latest_source_updated_at(
            links, applications, proposed_hires, offers
        ),
        provider_version="hr04.recruitment-handoff-self.1",
        authority="HR04_RECRUITMENT_AUTHORITY",
    )


def hr05_self_provider(context: SelfIdentityContext):
    """Read onboarding progress, staff-visible tasks and probation outcome."""

    from hr_onboarding.models import (
        HrOnboardingCase,
        HrOnboardingTaskInstance,
        HrProbationCase,
    )

    cases = list(
        HrOnboardingCase.objects.filter(
            tenant_id=context.tenant_id,
            hr03_staff_master_id=context.staff_id,
        ).order_by("-updated_at")[:20]
    )
    case_ids = [row.id for row in cases]
    tasks = list(
        HrOnboardingTaskInstance.objects.filter(
            tenant_id=context.tenant_id,
            case_id__in=case_ids,
        ).select_related("definition").order_by("due_at", "created_at")[:100]
    ) if case_ids else []
    probation = list(
        HrProbationCase.objects.filter(
            tenant_id=context.tenant_id,
            staff_master_id=context.staff_id,
        ).order_by("-updated_at")[:20]
    )

    return _ok(
        {
            "onboardingCases": [
                {
                    "id": _identifier(row.id),
                    "caseNo": row.case_no,
                    "status": row.status,
                    "currentStageCode": row.current_stage_code,
                    "activationStatus": row.activation_status,
                    "expectedReportDate": _iso(row.expected_report_date),
                    "actualReportAt": _iso(row.actual_report_at),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in cases
            ],
            "tasks": [
                {
                    "id": _identifier(row.id),
                    "caseId": _identifier(row.case_id),
                    "code": row.definition.code,
                    "title": row.definition.title,
                    "status": row.status,
                    "availableAt": _iso(row.available_at),
                    "dueAt": _iso(row.due_at),
                    "completedAt": _iso(row.completed_at),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in tasks
            ],
            "probationCases": [
                {
                    "id": _identifier(row.id),
                    "status": row.status,
                    "result": row.result,
                    "startDate": _iso(row.start_date),
                    "plannedEndDate": _iso(row.planned_end_date),
                    "actualEndDate": _iso(row.actual_end_date),
                    "extensionCount": row.extension_count,
                    "updatedAt": _iso(row.updated_at),
                }
                for row in probation
            ],
        },
        source_updated_at=_latest_source_updated_at(cases, tasks, probation),
        provider_version="hr05.onboarding-authority-self.1",
        authority="HR05_ONBOARDING_AUTHORITY",
    )


def hr06_self_provider(context: SelfIdentityContext):
    """Read this staff member's personnel-change cases without approval internals."""

    from hr_changes.models import HrPersonnelChangeCase

    cases = list(
        HrPersonnelChangeCase.objects.filter(
            tenant_id=context.tenant_id,
            staff_master_id=context.staff_id,
        ).select_related("action_id", "reason_id").order_by("-updated_at")[:50]
    )
    return _ok(
        {
            "changeCases": [
                {
                    "id": _identifier(row.id),
                    "caseNo": row.case_no,
                    "actionCode": row.action_id.code,
                    "reasonCode": row.reason_id.code,
                    "status": row.status,
                    "requestedEffectiveAt": _iso(row.requested_effective_at),
                    "approvedEffectiveAt": _iso(row.approved_effective_at),
                    "submittedAt": _iso(row.submitted_at),
                    "approvedAt": _iso(row.approved_at),
                    "appliedAt": _iso(row.applied_at),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in cases
            ]
        },
        source_updated_at=_latest_source_updated_at(cases),
        provider_version="hr06.change-authority-self.1",
        authority="HR06_CHANGE_AUTHORITY",
    )


def hr08_self_provider(context: SelfIdentityContext):
    """Read external-engagement history for the resolved canonical person."""

    from hr_external.models import HrExternalEngagement

    engagements = list(
        HrExternalEngagement.objects.filter(
            tenant_id=context.tenant_id,
            person_id=context.person_id,
        ).order_by("-updated_at")[:50]
    )
    return _ok(
        {
            "externalEngagements": [
                {
                    "id": _identifier(row.id),
                    "engagementNo": row.engagement_no,
                    "purpose": row.purpose,
                    "hostOrganizationId": _identifier(row.host_organization_id),
                    "startAt": _iso(row.start_at),
                    "endAt": _iso(row.end_at),
                    "reviewAt": _iso(row.review_at),
                    "agreementStatus": row.agreement_status,
                    "status": row.status,
                    "riskLevel": row.current_risk_level,
                    "updatedAt": _iso(row.updated_at),
                }
                for row in engagements
            ]
        },
        source_updated_at=_latest_source_updated_at(engagements),
        provider_version="hr08.external-authority-self.1",
        authority="HR08_EXTERNAL_AUTHORITY",
    )


def hr11_self_provider(context: SelfIdentityContext):
    """Read attendance, leave balance and timesheet facts for SELF.

    HR11 currently stores its staff key as the resolved legacy employee id.
    Missing identity mapping is therefore UNAVAILABLE, never a plausible empty
    attendance history.
    """

    from hr_self.services.provider_gateway import SelfProviderResult

    if context.legacy_employee_id is None:
        return SelfProviderResult.unavailable(
            "SOURCE_IDENTITY_MAPPING_UNAVAILABLE",
            "HR11 requires a resolved legacy employee mapping",
            provider_version="hr11.time-authority-self.1",
        )

    from hr_time.models import (
        HrAttendanceDayFact,
        HrLeaveAccount,
        HrLeaveLedgerEntry,
        HrTimeSheetPeriod,
    )

    staff_key = context.legacy_employee_id
    day_facts = list(
        HrAttendanceDayFact.objects.filter(
            tenant_id=context.tenant_id,
            staff_master_id=staff_key,
        ).order_by("-business_date")[:62]
    )
    accounts = list(
        HrLeaveAccount.objects.filter(
            tenant_id=context.tenant_id,
            staff_master_id=staff_key,
        ).select_related("leave_type").order_by("-account_year", "leave_type__code")[:50]
    )
    account_ids = [row.id for row in accounts]
    ledger_rows = list(
        HrLeaveLedgerEntry.objects.filter(
            tenant_id=context.tenant_id,
            account_id__in=account_ids,
        ).order_by("account_id", "-effective_date", "-created_at")
    ) if account_ids else []
    latest_balance = {}
    for row in ledger_rows:
        latest_balance.setdefault(row.account_id, row.balance_after)
    timesheets = list(
        HrTimeSheetPeriod.objects.filter(
            tenant_id=context.tenant_id,
            staff_master_id=staff_key,
        ).order_by("-end_date", "-created_at")[:24]
    )

    return _ok(
        {
            "attendanceDayFacts": [
                {
                    "id": _identifier(row.id),
                    "businessDate": _iso(row.business_date),
                    "status": row.status,
                    "expectedMinutes": row.expected_minutes,
                    "actualMinutes": row.actual_minutes,
                    "creditedMinutes": row.credited_minutes,
                    "authorizedAbsenceMinutes": row.authorized_absence_minutes,
                    "overtimeMinutesCandidate": row.overtime_minutes_candidate,
                    "finalized": bool(row.finalized),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in day_facts
            ],
            "leaveAccounts": [
                {
                    "id": _identifier(row.id),
                    "leaveTypeCode": row.leave_type.code,
                    "leaveTypeName": row.leave_type.name,
                    "accountYear": row.account_year,
                    "status": row.status,
                    "balance": _amount(latest_balance.get(row.id, Decimal("0"))),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in accounts
            ],
            "timesheets": [
                {
                    "id": _identifier(row.id),
                    "startDate": _iso(row.start_date),
                    "endDate": _iso(row.end_date),
                    "status": row.status,
                    "submittedAt": _iso(row.submitted_at),
                    "approvedAt": _iso(row.approved_at),
                    "updatedAt": _iso(row.updated_at),
                }
                for row in timesheets
            ],
        },
        source_updated_at=_latest_source_updated_at(
            day_facts, accounts, ledger_rows, timesheets
        ),
        provider_version="hr11.time-authority-self.1",
        authority="HR11_TIME_AUTHORITY",
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
