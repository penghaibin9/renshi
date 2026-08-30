"""HR14 source-owned participant for HR16 exit effects.

The provider is replay-safe across lost participant receipts: an HR16 exit
appends one sealed ``EXIT_CLOSURE`` successor and never shortens or overwrites
the original appointment row.  Retries return that same closure evidence.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Exists, OuterRef, Q

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

    successor_rows = PositionAppointmentFact.objects.filter(
        tenant_id=tenant_id, supersedes_fact_id=OuterRef("id")
    )
    future_conflict = (
        PositionAppointmentFact.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            person_id=case.person_id,
            status__in=active_statuses,
            effective_from__gte=boundary,
        )
        .annotate(has_successor=Exists(successor_rows))
        .filter(has_successor=False)
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
            effective_to=boundary,
            fact_kind=PositionAppointmentFact.FactKind.EXIT_CLOSURE,
        )
        .order_by("effective_from", "id")
    )
    for appointment in already_ended:
        if not appointment.verify_content_hash():
            raise ValueError("HR14_EXIT_FACT_HASH_MISMATCH")
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
        .annotate(has_successor=Exists(successor_rows))
        .filter(has_successor=False)
        .order_by("effective_from", "id")
    )

    for appointment in appointments:
        if not appointment.verify_content_hash():
            raise ValueError("HR14_EXIT_FACT_HASH_MISMATCH")
        receipt = dict(appointment.effect_receipt_json or {})
        existing_exit = receipt.get("hr16Exit")
        if existing_exit is not None and (
            not isinstance(existing_exit, dict)
            or not _same_exit_closure(existing_exit, closure)
        ):
            raise ValueError(
                "HR14_EXIT_RECEIPT_CONFLICT: appointment already carries a different exit closure"
            )
        if not actor_user_id:
            raise ValueError("HR14_EXIT_ACTOR_REQUIRED")
        receipt["hr16Exit"] = closure
        closed_fact = PositionAppointmentFact.objects.create(
            tenant_id=tenant_id,
            appointment_no=f"END-{appointment.id.hex[:12]}-{exit_fact.id.hex[:12]}",
            person_id=appointment.person_id,
            position_instance_id=appointment.position_instance_id,
            application_case_id=appointment.application_case_id,
            reservation_id=appointment.reservation_id,
            level_code=appointment.level_code,
            effective_from=appointment.effective_from,
            effective_to=boundary,
            supersedes_fact_id=appointment.id,
            fact_kind=PositionAppointmentFact.FactKind.EXIT_CLOSURE,
            revision_reason=f"HR16 exit fact {exit_fact.id}",
            idempotency_key=f"hr14-exit:{exit_fact.id}:{appointment.id}",
            effect_receipt_json=receipt,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        closed_fact.seal(
            status=PositionAppointmentFact.Status.ENDED,
            actor_user_id=actor_user_id,
            authority_receipt={
                "permissionCode": "hr.appointment.term",
                "authorityRef": f"HR16_EXIT:{exit_fact.id}",
                "actorUserId": actor_user_id,
                "evidence": closure,
            },
        )
        from hr_appointment.authority_registry import EVENT_FACT_ENDED
        from hr_appointment.services.fact_authority_service import emit_fact_event

        emit_fact_event(fact=closed_fact, event_name=EVENT_FACT_ENDED)
        ended_ids.append(str(closed_fact.id))

    return {
        "provider": "hr14-internal-exit-v1",
        "tenantId": int(tenant_id),
        "personId": str(case.person_id),
        "exitFactId": str(exit_fact.id),
        "employmentEndDate": boundary.isoformat(),
        "endedAppointmentIds": ended_ids,
        "endedAppointmentCount": len(ended_ids),
    }
