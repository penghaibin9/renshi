"""HR15 source-owned participant for HR16 exit settlement.

Settlement is derived from the latest formal payroll period ending on/before the
employment boundary. A FINALIZED result is the base amount; ADJUSTED facts are
append-only deltas and are accumulated only when their supersedes chain resolves
to that base result. The payroll profile close timestamp becomes the durable
replay cutoff, so adjustments created after an already-committed exit settlement
cannot change a recovered participant receipt.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact


def _validated_adjustment_chain(*, base, adjustments):
    """Return validated adjustments whose chain terminates at the one base fact."""
    by_id = {str(base.id): base}
    by_id.update({str(item.id): item for item in adjustments})

    for item in adjustments:
        if item.currency_code != base.currency_code:
            raise ValueError("HR15_EXIT_ADJUSTMENT_CURRENCY_CONFLICT")
        if not item.supersedes_result_id:
            raise ValueError("HR15_EXIT_ADJUSTMENT_SOURCE_REQUIRED")

        seen = {str(item.id)}
        cursor = item
        while str(cursor.id) != str(base.id):
            parent_id = str(cursor.supersedes_result_id or "")
            if not parent_id or parent_id not in by_id:
                raise ValueError("HR15_EXIT_ADJUSTMENT_ORPHAN_CONFLICT")
            if parent_id in seen:
                raise ValueError("HR15_EXIT_ADJUSTMENT_CYCLE_CONFLICT")
            seen.add(parent_id)
            cursor = by_id[parent_id]

    return adjustments


def _settlement_amounts(*, base, adjustments):
    gross = Decimal(base.gross_amount)
    deduction = Decimal(base.deduction_amount)
    net = Decimal(base.net_amount)
    for item in adjustments:
        gross += Decimal(item.gross_amount)
        deduction += Decimal(item.deduction_amount)
        net += Decimal(item.net_amount)
    if net != gross - deduction:
        raise ValueError("HR15_EXIT_SETTLEMENT_AMOUNT_MISMATCH")
    return gross, deduction, net


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

    period = (
        PayrollPeriod.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            end_date__lte=boundary,
            status__in=(PayrollPeriod.Status.FINALIZED, PayrollPeriod.Status.CLOSED),
        )
        .order_by("-end_date", "-start_date", "-id")
        .first()
    )
    if period is None:
        raise ExitParticipantUnavailable(
            "no finalized HR15 payroll period exists at or before the employment end date"
        )

    fact_qs = PayrollResultFact.objects.select_for_update().filter(
        tenant_id=tenant_id,
        staff_id=staff.id,
        payroll_period_id=period.id,
    )
    if already_closed:
        # The profile close is the durable settlement commit marker. Facts
        # appended afterwards belong to later correction/reconciliation, not to
        # the lost participant receipt we are recovering.
        fact_qs = fact_qs.filter(created_at__lte=profile.updated_at)

    reversed_exists = fact_qs.filter(status=PayrollResultFact.Status.REVERSED).exists()
    if reversed_exists:
        raise ValueError("HR15_EXIT_REVERSED_RESULT_REQUIRES_RECONCILIATION")

    bases = list(
        fact_qs.filter(status=PayrollResultFact.Status.FINALIZED).order_by("created_at", "id")
    )
    if not bases:
        raise ExitParticipantUnavailable(
            "no finalized HR15 payroll result exists for this staff member in the latest eligible payroll period"
        )
    if len(bases) != 1:
        raise ValueError("HR15_EXIT_MULTIPLE_BASE_RESULTS_CONFLICT")
    base = bases[0]

    adjustments = list(
        fact_qs.filter(status=PayrollResultFact.Status.ADJUSTED).order_by("created_at", "id")
    )
    _validated_adjustment_chain(base=base, adjustments=adjustments)
    gross_amount, deduction_amount, net_amount = _settlement_amounts(
        base=base,
        adjustments=adjustments,
    )

    if not already_closed:
        profile.effective_to = boundary
        profile.status = PayrollProfile.Status.ENDED
        profile.updated_by = actor_user_id
        profile.save(
            update_fields=["effective_to", "status", "updated_by", "updated_at"]
        )

    evidence_ids = [str(base.id), *(str(item.id) for item in adjustments)]
    return {
        "provider": "hr15-internal-exit-settlement-v2",
        "tenantId": int(tenant_id),
        "personId": str(case.person_id),
        "staffId": str(staff.id),
        "exitFactId": str(exit_fact.id),
        "employmentEndDate": boundary.isoformat(),
        "payrollProfileId": str(profile.id),
        "payrollProfileClosed": True,
        "settlementSnapshotAt": profile.updated_at.isoformat(),
        "payrollResultId": str(base.id),
        "payrollResultNo": base.result_no,
        "adjustmentResultIds": [str(item.id) for item in adjustments],
        "payrollEvidenceIds": evidence_ids,
        "payrollPeriodId": str(period.id),
        "payrollPeriodCode": period.period_code,
        "currencyCode": base.currency_code,
        "grossAmount": str(gross_amount),
        "deductionAmount": str(deduction_amount),
        "netAmount": str(net_amount),
    }
