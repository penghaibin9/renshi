"""
hr_external/services/hiring_service.py —— 聘用审批流程（S5，总册 §32-43）。

状态机（§34）：DRAFT→VALIDATING→SUBMITTED→UNDER_COLLEGE_REVIEW→UNDER_HR_REVIEW
→UNDER_SCHOOL_APPROVAL→APPROVED→WAITING_AGREEMENT→READY_TO_ACTIVATE→ACTIVATED。
异常：RETURNED/REJECTED/WITHDRAWN/CANCELLED。

Activation（§43）事务：
1. lock case；2. revalidate dates；3. confirm HR07 agreement state；
4. create Engagement；5. create Assignment(s)；6. external worker directory projection（S9）；
7. emit ExternalEngagementActivated（LifecycleEvent）；8. access provisioning requests（S6）；
9. case → ACTIVATED。
外部 IAM/教务不在核心 DB transaction 内同步等待（§43）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction

from hr_external.constants import (
    AgreementProviderStatus,
    ExternalAssignmentStatus,
    ExternalAssignmentType,
    ExternalEngagementStatus,
    ExternalHiringStatus,
)
from hr_external.integrations.hr07 import AgreementProvider
from hr_external.models import (
    HrExternalEngagement,
    HrExternalEngagementAssignment,
    HrExternalHiringCase,
    HrExternalLifecycleEvent,
    HrExternalTeacherProfile,
)
from hr_external.services.compliance_service import ComplianceService


class InvalidHiringState(Exception):
    code = "VERSION_CONFLICT"


class HiringCaseNotFound(Exception):
    code = "EXTERNAL_HIRING_CASE_NOT_FOUND"


class AgreementNotReady(Exception):
    code = "EXTERNAL_AGREEMENT_NOT_READY"


class ComplianceBlocked(Exception):
    code = "EXTERNAL_ETHICS_REVIEW_FAILED"


_HIRING_TRANSITIONS = {
    ExternalHiringStatus.DRAFT: {
        ExternalHiringStatus.VALIDATING,
        ExternalHiringStatus.SUBMITTED,
        ExternalHiringStatus.CANCELLED,
        ExternalHiringStatus.WITHDRAWN,
    },
    ExternalHiringStatus.VALIDATING: {
        ExternalHiringStatus.SUBMITTED,
        ExternalHiringStatus.RETURNED,
        ExternalHiringStatus.CANCELLED,
    },
    ExternalHiringStatus.SUBMITTED: {
        ExternalHiringStatus.UNDER_COLLEGE_REVIEW,
        ExternalHiringStatus.UNDER_HR_REVIEW,
        ExternalHiringStatus.RETURNED,
        ExternalHiringStatus.WITHDRAWN,
    },
    ExternalHiringStatus.UNDER_COLLEGE_REVIEW: {
        ExternalHiringStatus.UNDER_HR_REVIEW,
        ExternalHiringStatus.RETURNED,
        ExternalHiringStatus.REJECTED,
        ExternalHiringStatus.WITHDRAWN,
    },
    ExternalHiringStatus.UNDER_HR_REVIEW: {
        ExternalHiringStatus.UNDER_SCHOOL_APPROVAL,
        ExternalHiringStatus.RETURNED,
        ExternalHiringStatus.REJECTED,
    },
    ExternalHiringStatus.UNDER_SCHOOL_APPROVAL: {
        ExternalHiringStatus.APPROVED,
        ExternalHiringStatus.RETURNED,
        ExternalHiringStatus.REJECTED,
    },
    ExternalHiringStatus.APPROVED: {
        ExternalHiringStatus.WAITING_AGREEMENT,
        ExternalHiringStatus.CANCELLED,
    },
    ExternalHiringStatus.WAITING_AGREEMENT: {
        ExternalHiringStatus.READY_TO_ACTIVATE,
        ExternalHiringStatus.RETURNED,
        ExternalHiringStatus.CANCELLED,
    },
    ExternalHiringStatus.READY_TO_ACTIVATE: {
        ExternalHiringStatus.ACTIVATED,
        ExternalHiringStatus.CANCELLED,
    },
    ExternalHiringStatus.ACTIVATED: set(),
}


class HiringService:
    def __init__(self, compliance: Optional[ComplianceService] = None):
        self.compliance = compliance or ComplianceService()

    @staticmethod
    def validate_transition(current: str, target: str) -> bool:
        return target in _HIRING_TRANSITIONS.get(current, set())

    def _transition(self, case: HrExternalHiringCase, target: str, actor_id=None):
        if not self.validate_transition(case.status, target):
            raise InvalidHiringState(f"illegal transition {case.status} -> {target}")
        case.status = target
        case.save(update_fields=["status", "updated_at"])

    def submit(self, case: HrExternalHiringCase):
        self._transition(case, ExternalHiringStatus.SUBMITTED)

    def return_to_draft(self, case: HrExternalHiringCase, reason: str = ""):
        if case.status not in (
            ExternalHiringStatus.SUBMITTED,
            ExternalHiringStatus.UNDER_COLLEGE_REVIEW,
            ExternalHiringStatus.UNDER_HR_REVIEW,
            ExternalHiringStatus.UNDER_SCHOOL_APPROVAL,
            ExternalHiringStatus.WAITING_AGREEMENT,
        ):
            raise InvalidHiringState("cannot return in current status")
        self._transition(case, ExternalHiringStatus.RETURNED)

    def college_approve(self, case: HrExternalHiringCase):
        self._transition(case, ExternalHiringStatus.UNDER_HR_REVIEW)

    def hr_approve(self, case: HrExternalHiringCase):
        self._transition(case, ExternalHiringStatus.UNDER_SCHOOL_APPROVAL)

    def school_approve(self, case: HrExternalHiringCase):
        if case.status != ExternalHiringStatus.UNDER_SCHOOL_APPROVAL:
            raise InvalidHiringState("case not under school approval")
        profile = _profile_for_case(case)
        if profile is None:
            raise HiringCaseNotFound("proposed person has no external profile")
        result = self.compliance.run_checks(
            tenant_id=case.tenant_id,
            case=case,
            profile=profile,
            category=case.category_id,
        )
        if result.has_blocker:
            raise ComplianceBlocked(
                "审批前检查存在 BLOCKER：" + "; ".join(c.message for c in result.blockers)
            )
        self._transition(case, ExternalHiringStatus.APPROVED)

    def reject(self, case: HrExternalHiringCase):
        self._transition(case, ExternalHiringStatus.REJECTED)

    def wait_agreement(self, case: HrExternalHiringCase):
        if case.status != ExternalHiringStatus.APPROVED:
            raise InvalidHiringState("case not approved")
        self._transition(case, ExternalHiringStatus.WAITING_AGREEMENT)

    def _agreement_result(
        self,
        *,
        case: HrExternalHiringCase,
        agreement_id: str,
    ):
        provider = AgreementProvider()
        result = provider.resolve_agreement(
            tenant_id=case.tenant_id,
            agreement_type_code=case.category_id.agreement_type_code,
            agreement_id=agreement_id,
            subject_reference_type="HR08_HIRING_CASE",
            subject_reference_id=str(case.id),
        )
        status = provider.agreement_status_code(result)
        return result, status

    def agreement_gate(
        self,
        *,
        tenant_id: int,
        agreement_type_code: str,
        agreement_id: str = "",
        subject_reference_type: str = "",
        subject_reference_id: str = "",
    ) -> bool:
        """Compatibility boolean gate backed by the real HR07 Provider."""
        provider = AgreementProvider()
        result = provider.resolve_agreement(
            tenant_id=tenant_id,
            agreement_type_code=agreement_type_code,
            agreement_id=agreement_id,
            subject_reference_type=subject_reference_type,
            subject_reference_id=subject_reference_id,
        )
        status = provider.agreement_status_code(result)
        return status in (
            AgreementProviderStatus.SIGNED.value,
            AgreementProviderStatus.ACTIVE.value,
        )

    @transaction.atomic
    def confirm_agreement(
        self,
        case: HrExternalHiringCase,
        *,
        agreement_id: str,
    ) -> HrExternalHiringCase:
        """Bind the exact HR07 external agreement and unlock activation."""
        locked = (
            HrExternalHiringCase.objects.select_for_update()
            .select_related("category_id")
            .filter(id=case.id, tenant_id=case.tenant_id)
            .first()
        )
        if locked is None:
            raise HiringCaseNotFound("hiring case not found inside tenant")
        if locked.status != ExternalHiringStatus.WAITING_AGREEMENT:
            raise InvalidHiringState("case not waiting for agreement")
        if not agreement_id:
            raise AgreementNotReady("agreement reference is required")

        _result, status = self._agreement_result(case=locked, agreement_id=agreement_id)
        if status not in (
            AgreementProviderStatus.SIGNED.value,
            AgreementProviderStatus.ACTIVE.value,
        ):
            raise AgreementNotReady("agreement not ready for activation")

        locked.agreement_id = str(agreement_id)
        locked.status = ExternalHiringStatus.READY_TO_ACTIVATE
        locked.save(update_fields=["agreement_id", "status", "updated_at"])
        return locked

    @transaction.atomic
    def activate(self, case: HrExternalHiringCase, *, actor_id=None) -> HrExternalEngagement:
        """Activate an external engagement only from a tenant-bound ready case."""
        case = (
            HrExternalHiringCase.objects.select_for_update()
            .select_related("category_id")
            .filter(id=case.id, tenant_id=case.tenant_id)
            .first()
        )
        if case is None:
            raise HiringCaseNotFound("hiring case not found inside tenant")
        if case.status != ExternalHiringStatus.READY_TO_ACTIVATE:
            raise InvalidHiringState("case not ready to activate")

        if case.requested_end and case.requested_start >= case.requested_end:
            raise InvalidHiringState("EXTERNAL_ENGAGEMENT_DATES_INVALID")
        if case.proposed_person_id is None:
            raise HiringCaseNotFound("proposed person missing")

        profile = HrExternalTeacherProfile.objects.filter(
            tenant_id=case.tenant_id,
            person_id_id=case.proposed_person_id_id,
        ).first()
        if profile is None:
            raise HiringCaseNotFound("external profile missing for proposed person")

        if case.category_id.agreement_requirement == "REQUIRED_BEFORE_ACTIVATION":
            if not case.agreement_id:
                raise AgreementNotReady("agreement reference missing")
            _result, agreement_status = self._agreement_result(
                case=case,
                agreement_id=case.agreement_id,
            )
            if agreement_status not in (
                AgreementProviderStatus.SIGNED.value,
                AgreementProviderStatus.ACTIVE.value,
            ):
                raise AgreementNotReady("agreement not ready for activation")
        else:
            agreement_status = AgreementProviderStatus.NOT_REQUIRED.value

        eng = HrExternalEngagement.objects.create(
            tenant_id=case.tenant_id,
            engagement_no=f"E{case.case_no}",
            person_id_id=case.proposed_person_id_id,
            external_profile_id=profile,
            category_id=case.category_id,
            purpose=case.purpose,
            source_type="COLLEGE_RECOMMENDATION",
            source_case_id=str(case.id),
            host_organization_id=case.request_org_id,
            start_at=case.requested_start,
            end_at=case.requested_end,
            review_at=_default_review_at(case.requested_start, case.requested_end),
            workload_cap=case.estimated_workload,
            agreement_id=case.agreement_id,
            agreement_requirement=case.category_id.agreement_requirement,
            agreement_status=agreement_status,
            status=ExternalEngagementStatus.ACTIVE,
        )

        for idx, planned in enumerate(case.planned_assignments_json or []):
            HrExternalEngagementAssignment.objects.create(
                tenant_id=case.tenant_id,
                engagement_id=eng,
                organization_id=planned.get("organizationId") or case.request_org_id,
                assignment_type=planned.get("assignmentType") or ExternalAssignmentType.TEACHING,
                post_catalog_id=planned.get("postCatalogId"),
                role_title=planned.get("roleTitle") or "",
                is_primary=(idx == 0),
                start_at=eng.start_at,
                end_at=eng.end_at,
                workload_limit=planned.get("workloadLimit"),
                academic_scope_json=planned.get("academicScope") or {},
                status=ExternalAssignmentStatus.ACTIVE,
            )

        HrExternalLifecycleEvent.objects.create(
            tenant_id=case.tenant_id,
            event_type="ExternalEngagementActivated",
            event_version=1,
            aggregate_type="ExternalEngagement",
            aggregate_id=eng.id,
            aggregate_version=eng.version,
            engagement_id=eng,
            effective_at=eng.start_at,
            idempotency_key=f"activate:{case.id}",
            payload_json={"engagementId": str(eng.id), "caseId": str(case.id)},
            status="PUBLISHED",
        )

        self._transition(case, ExternalHiringStatus.ACTIVATED)
        return eng


def _profile_for_case(case: HrExternalHiringCase) -> Optional[HrExternalTeacherProfile]:
    if not case.proposed_person_id:
        return None
    return HrExternalTeacherProfile.objects.filter(
        tenant_id=case.tenant_id, person_id_id=case.proposed_person_id_id
    ).first()


def _default_review_at(start_at: date, end_at: Optional[date]) -> Optional[date]:
    if not end_at:
        return None
    from datetime import timedelta

    review = end_at - timedelta(days=90)
    return review if review > start_at else start_at
