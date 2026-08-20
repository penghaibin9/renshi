"""HR14 source-owned participant for HR16 exit effects.

The provider is replay-safe across lost participant receipts: appointments
already closed by the same HR16 exit business fact are returned as the same
successful evidence instead of disappearing from a retry because their current
status is now ENDED.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from hr_appointment.models import PositionAppointmentFact


def _same_exit_closure(existing: dict, expected: dict) -> bool:
    """Effect IDs may differ on recovery; the HR16 business closure must not."""
    return all(
        str(existing.get(key, "")) == str(expected.get(key, ""))
        for key in ("exitFactId", "exitCaseId", "employmentEndDate")
    )


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
    closure = {
        "exitFactId": str(exit_fact.id),
        "exitCaseId": str(case.id),
        "employmentEndDate": boundary.isoformat(),
        "effectId": str(effect.id),
    }

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

    # Recovery/replay path: an earlier worker may have committed the HR14 close
    # and crashed before HR16 persisted its participant SUCCESS receipt.
    ended_ids = []
    already_ended = list(
        PositionAppointmentFact.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            person_id=case.person_id,
            status=PositionAppointmentFact.Status.ENDED,
            effective_from__lt=boundary,
            effective_to=boundary,
        )
        .order_by("effective_from", "id")
    )
    for appointment in already_ended:
        existing_exit = dict(appointment.effect_receipt_json or {}).get("hr16Exit")
        if existing_exit is None:
            continue
        if not isinstance(existing_exit, dict) or not _same_exit_closure(
            existing_exit, closure
        ):
            raise ValueError(
                "HR14_EXIT_RECEIPT_CONFLICT: appointment already carries a different exit closure"
            )
        ended_ids.append(str(appointment.id))

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

    for appointment in appointments:
        receipt = dict(appointment.effect_receipt_json or {})
        existing_exit = receipt.get("hr16Exit")
        if existing_exit is not None and (
            not isinstance(existing_exit, dict)
            or not _same_exit_closure(existing_exit, closure)
        ):
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
