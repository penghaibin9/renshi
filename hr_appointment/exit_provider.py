"""HR14 source-owned participant for HR16 exit effects.

HR16 may request an HR14 participant, but it must not update HR14 tables itself.
This provider validates the already-effective HR16 exit fact, locks the person's
formal appointment facts, and closes only appointments that were effective at
the employment end boundary. Future effective appointments are treated as a
reconciliation conflict rather than silently left active after employment ends.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from hr_appointment.models import PositionAppointmentFact


@transaction.atomic
def exit_participant_provider(*, tenant_id, case, effect, actor_user_id=None):
    from hr_exit.models import ExitFact

    if str(effect.case_id) != str(case.id):
        raise ValueError("HR14_EXIT_EFFECT_CASE_MISMATCH")

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
        raise ValueError("HR14_EXIT_EFFECTIVE_FACT_REQUIRED")
    if exit_fact.employment_end_date != case.planned_employment_end_date:
        raise ValueError("HR14_EXIT_EFFECTIVE_DATE_MISMATCH")

    boundary = exit_fact.employment_end_date
    active_statuses = (
        PositionAppointmentFact.Status.EFFECTIVE,
        PositionAppointmentFact.Status.REVISED,
    )

    # A formal appointment that starts on/after the employment end date cannot
    # be closed by setting effective_to=boundary (the model requires end > start).
    # Surface it as an explicit conflict for reconciliation instead of hiding it.
    future_conflict = (
        PositionAppointmentFact.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            person_id=case.person_id,
            status__in=active_statuses,
            effective_from__gte=boundary,
        )
        .order_by("effective_from", "id")
        .first()
    )
    if future_conflict is not None:
        raise ValueError(
            "HR14_EXIT_FUTURE_APPOINTMENT_CONFLICT: "
            f"{future_conflict.appointment_no} starts {future_conflict.effective_from}"
        )

    appointments = list(
        PositionAppointmentFact.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            person_id=case.person_id,
            status__in=active_statuses,
            effective_from__lt=boundary,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=boundary))
        .order_by("effective_from", "id")
    )

    ended_ids = []
    for appointment in appointments:
        receipt = dict(appointment.effect_receipt_json or {})
        existing_exit = receipt.get("hr16Exit")
        closure = {
            "exitFactId": str(exit_fact.id),
            "exitCaseId": str(case.id),
            "employmentEndDate": boundary.isoformat(),
            "effectId": str(effect.id),
        }
        if existing_exit is not None and existing_exit != closure:
            raise ValueError(
                "HR14_EXIT_RECEIPT_CONFLICT: appointment already carries a different exit closure"
            )
        receipt["hr16Exit"] = closure
        appointment.effective_to = boundary
        appointment.status = PositionAppointmentFact.Status.ENDED
        appointment.effect_receipt_json = receipt
        appointment.updated_by = actor_user_id
        appointment.save(
            update_fields=[
                "effective_to",
                "status",
                "effect_receipt_json",
                "updated_by",
                "updated_at",
            ]
        )
        ended_ids.append(str(appointment.id))

    return {
        "provider": "hr14-internal-exit-v1",
        "tenantId": int(tenant_id),
        "personId": str(case.person_id),
        "exitFactId": str(exit_fact.id),
        "employmentEndDate": boundary.isoformat(),
        "endedAppointmentIds": ended_ids,
        "endedAppointmentCount": len(ended_ids),
    }
