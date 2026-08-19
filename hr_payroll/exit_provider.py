"""HR15 source-owned participant for HR16 exit settlement.

The exit domain must never manufacture payroll amounts. This provider therefore
acts only after a formal HR15 payroll result exists at or before the employment
end date. It then closes the active payroll profile at the exit boundary and
returns an auditable receipt referencing the existing immutable payroll result.
If formal payroll evidence is not ready, the participant remains retryable
UNAVAILABLE instead of pretending settlement succeeded.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact


@transaction.atomic
def exit_settlement_participant_provider(*, tenant_id, case, effect, actor_user_id=None):
    from hr_exit.models import ExitFact
    from hr_exit.services.participant_service import ExitParticipantUnavailable
    from hr_staff.models import HrStaffMaster

    if str(effect.case_id) != str(case.id):
        raise ValueError("HR15_EXIT_EFFECT_CASE_MISMATCH")

    exit_fact = (
        ExitFact.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            source_case_id=case.id,
            person_id=case.person_id,
            status=ExitFact.Status.EFFECTIVE,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if exit_fact is None:
        raise ValueError("HR15_EXIT_EFFECTIVE_FACT_REQUIRED")
    if exit_fact.employment_end_date != case.planned_employment_end_date:
        raise ValueError("HR15_EXIT_EFFECTIVE_DATE_MISMATCH")

    boundary = exit_fact.employment_end_date
    staff = (
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            person_id_id=case.person_id,
        )
        .order_by("id")
        .first()
    )
    if staff is None:
        raise ValueError("HR15_EXIT_STAFF_MAPPING_REQUIRED")

    future_profile = (
        PayrollProfile.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            staff_id=staff.id,
            status=PayrollProfile.Status.ACTIVE,
            effective_from__gte=boundary,
        )
        .order_by("effective_from", "id")
        .first()
    )
    if future_profile is not None:
        raise ValueError(
            "HR15_EXIT_FUTURE_PAYROLL_PROFILE_CONFLICT: "
            f"{future_profile.payroll_identity_no} starts {future_profile.effective_from}"
        )

    profile = (
        PayrollProfile.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            staff_id=staff.id,
            status=PayrollProfile.Status.ACTIVE,
            effective_from__lt=boundary,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=boundary))
        .order_by("-effective_from", "id")
        .first()
    )
    already_closed = False
    if profile is None:
        profile = (
            PayrollProfile.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                staff_id=staff.id,
                status=PayrollProfile.Status.ENDED,
                effective_to=boundary,
            )
            .order_by("-effective_from", "id")
            .first()
        )
        already_closed = profile is not None
    if profile is None:
        raise ValueError("HR15_EXIT_ACTIVE_PAYROLL_PROFILE_REQUIRED")

    finalized_period_ids = list(
        PayrollPeriod.objects.filter(
            tenant_id=tenant_id,
            end_date__lte=boundary,
            status__in=(PayrollPeriod.Status.FINALIZED, PayrollPeriod.Status.CLOSED),
        ).values_list("id", flat=True)
    )
    if not finalized_period_ids:
        raise ExitParticipantUnavailable(
            "no finalized HR15 payroll period exists at or before the employment end date"
        )

    result = (
        PayrollResultFact.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            staff_id=staff.id,
            payroll_period_id__in=finalized_period_ids,
            status__in=(PayrollResultFact.Status.FINALIZED, PayrollResultFact.Status.ADJUSTED),
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if result is None:
        raise ExitParticipantUnavailable(
            "no finalized HR15 payroll result exists for this staff member by the employment end date"
        )

    period = PayrollPeriod.objects.get(
        tenant_id=tenant_id,
        id=result.payroll_period_id,
    )

    if not already_closed:
        profile.effective_to = boundary
        profile.status = PayrollProfile.Status.ENDED
        profile.updated_by = actor_user_id
        profile.save(
            update_fields=["effective_to", "status", "updated_by", "updated_at"]
        )

    return {
        "provider": "hr15-internal-exit-settlement-v1",
        "tenantId": int(tenant_id),
        "personId": str(case.person_id),
        "staffId": str(staff.id),
        "exitFactId": str(exit_fact.id),
        "employmentEndDate": boundary.isoformat(),
        "payrollProfileId": str(profile.id),
        "payrollProfileClosed": True,
        "payrollResultId": str(result.id),
        "payrollResultNo": result.result_no,
        "payrollPeriodId": str(period.id),
        "payrollPeriodCode": period.period_code,
        "currencyCode": result.currency_code,
        "netAmount": str(result.net_amount),
    }
