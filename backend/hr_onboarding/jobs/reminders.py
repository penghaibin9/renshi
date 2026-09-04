"""
hr_onboarding/jobs/reminders.py

定时提醒（05 §38 通知 + §49 可观测）：
- probation_due：试用 30 天内到期 → REVIEW_DUE 提示（不直接改状态，交由业务动作）；
- report_reminder：预计报到临近且未确认 → 风险提示。
显式 tenant，后台任务不依赖当前 request。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.apps import apps
from django.db.models import Count
from django.utils import timezone

logger = logging.getLogger(__name__)


def probation_due(*, tenant_id: int, within_days: int = 30) -> list[dict]:
    """试用到期提醒（只读查询，输出提醒清单）。"""
    from hr_onboarding.constants import ProbationStatus
    from hr_onboarding.models import HrProbationCase

    today = timezone.localdate()
    due = HrProbationCase.objects.filter(
        tenant_id=tenant_id,
        status__in=(
            ProbationStatus.IN_PROGRESS,
            ProbationStatus.NOT_STARTED,
            ProbationStatus.UNDER_REVIEW,
        ),
        planned_end_date__lte=today + timedelta(days=within_days),
    )
    return [
        {
            "probation_id": str(p.id),
            "staff_master_id": str(p.staff_master_id) if p.staff_master_id else None,
            "planned_end_date": p.planned_end_date.isoformat(),
            "days_left": (p.planned_end_date - today).days,
        }
        for p in due
    ]


def report_risk(*, tenant_id: int, within_days: int = 7) -> list[dict]:
    """
    HR05-01 风险（总册 §9.8）。

    风险只读计算、不推进业务状态。HR04 Offer 仍由 HR04 持有，HR05 仅按
    tenant/source 关联展示；材料、Portal、延期与岗位预占均读取各自权威事实。
    """
    from hr_onboarding.constants import (
        CaseStatus,
        MaterialBlockingPhase,
        MaterialStatus,
        RiskCode,
    )
    from hr_onboarding.models import (
        HrOnboardingCase,
        HrOnboardingMaterial,
        HrOnboardingMaterialRequirement,
    )
    from hr_structure.models import HrPositionReservation

    risks = []
    today = timezone.localdate()
    now = timezone.now()
    horizon_date = today + timedelta(days=within_days)
    horizon_at = now + timedelta(days=within_days)
    terminal_statuses = {
        CaseStatus.CONFIRMED,
        CaseStatus.DECLINED,
        CaseStatus.NO_SHOW,
        CaseStatus.CANCELLED,
        CaseStatus.PROBATION_FAILED,
    }
    cases = list(
        HrOnboardingCase.objects.filter(tenant_id=tenant_id)
        .exclude(status__in=terminal_statuses)
        .select_related("position_reservation_id", "portal_access", "template_version")
        .annotate(report_delay_count=Count("report_delays"))
        .order_by("case_no", "id")
    )

    template_ids = {case.template_version_id for case in cases if case.template_version_id}
    requirements_by_template = defaultdict(list)
    for requirement in HrOnboardingMaterialRequirement.objects.filter(
        tenant_id=tenant_id,
        template_version_id__in=template_ids,
        required=True,
        blocking_phase__in=(
            MaterialBlockingPhase.PRE_REPORT,
            MaterialBlockingPhase.REPORT,
            MaterialBlockingPhase.ACTIVATION,
        ),
    ):
        requirements_by_template[requirement.template_version_id].append(requirement)

    material_status_by_case_requirement = {
        (material.case_id, material.requirement_id): material.status
        for material in HrOnboardingMaterial.objects.filter(
            tenant_id=tenant_id,
            case_id__in=[case.id for case in cases],
        )
    }

    ready_or_later = {
        CaseStatus.READY_TO_REPORT,
        CaseStatus.REPORT_SCHEDULED,
        CaseStatus.REPORTED,
        CaseStatus.VERIFYING,
        CaseStatus.READY_FOR_ACTIVATION,
        CaseStatus.ACTIVATING,
        CaseStatus.ACTIVE,
        CaseStatus.ONBOARDING_IN_PROGRESS,
        CaseStatus.ONBOARDING_COMPLETED,
        CaseStatus.PROBATION,
        CaseStatus.PROBATION_EXTENDED,
    }
    acceptable_material_statuses = {MaterialStatus.VERIFIED, MaterialStatus.WAIVED}

    def add_case_risk(case, risk, **details):
        risks.append(
            {
                "case_id": str(case.id),
                "case_no": case.case_no,
                "risk": str(risk),
                "status": case.status,
                **details,
            }
        )

    for case in cases:
        if (
            case.expected_report_date
            and case.expected_report_date <= horizon_date
            and case.status not in ready_or_later
        ):
            add_case_risk(
                case,
                RiskCode.REPORT_DATE_NEAR_NO_CONFIRM,
                expected_report_date=case.expected_report_date.isoformat(),
                days_left=(case.expected_report_date - today).days,
            )

        reservation = getattr(case, "position_reservation_id", None)
        if (
            reservation
            and reservation.status == HrPositionReservation.Status.HELD
            and reservation.expires_at <= horizon_at
        ):
            add_case_risk(
                case,
                RiskCode.POSITION_RESERVATION_EXPIRING,
                reservation_id=str(reservation.id),
                expires_at=reservation.expires_at.isoformat(),
            )

        missing = [
            requirement
            for requirement in requirements_by_template.get(case.template_version_id, ())
            if material_status_by_case_requirement.get((case.id, requirement.id))
            not in acceptable_material_statuses
        ]
        if missing:
            add_case_risk(
                case,
                RiskCode.MISSING_BLOCKING_DOCUMENT,
                missing_material_types=sorted(row.material_type for row in missing),
            )

        portal = getattr(case, "portal_access", None)
        if (
            case.expected_report_date
            and case.expected_report_date <= horizon_date
            and (portal is None or portal.last_used_at is None)
        ):
            add_case_risk(case, RiskCode.PORTAL_NOT_ACTIVATED)

        if case.report_delay_count >= 2:
            add_case_risk(
                case,
                RiskCode.DELAYED_MULTIPLE_TIMES,
                delay_count=case.report_delay_count,
            )

    if apps.is_installed("hr_recruitment"):
        from hr_recruitment.constants import OfferStatus
        from hr_recruitment.models import HrRecruitmentOffer

        cases_by_proposed = {
            str(case.hr04_proposed_hire_id): case
            for case in cases
            if case.hr04_proposed_hire_id
        }
        offers = HrRecruitmentOffer.objects.filter(
            tenant_id=tenant_id,
            status__in=(OfferStatus.ISSUED, OfferStatus.VIEWED),
            expires_at__isnull=False,
            expires_at__lte=horizon_at,
        ).order_by("expires_at", "offer_no", "id")
        for offer in offers:
            case = cases_by_proposed.get(str(offer.proposed_hire_id_id))
            risks.append(
                {
                    "case_id": str(case.id) if case else None,
                    "case_no": case.case_no if case else "",
                    "risk": str(RiskCode.OFFER_EXPIRING),
                    "status": case.status if case else offer.status,
                    "offer_id": str(offer.id),
                    "offer_no": offer.offer_no,
                    "expires_at": offer.expires_at.isoformat(),
                }
            )

    return risks
