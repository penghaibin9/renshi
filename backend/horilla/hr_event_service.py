"""Durable emitter for events registered in GlobalEventRegistry."""

from __future__ import annotations

import uuid

from horilla.hr_event_registry import global_event_registry


def emit_registered_event(*, tenant_id: int, event_name: str, payload: dict, version: int = 1, correlation_id: str = ""):
    """Persist a registered cross-domain event through the shared HR outbox facade."""
    global_event_registry.get(event_name, version)
    from hr_staff.models import HrOutboxEvent

    body = dict(payload or {})
    body.setdefault("eventVersion", version)
    return HrOutboxEvent.objects.create(
        tenant_id=tenant_id,
        event_type=event_name,
        payload_json=body,
        correlation_id=correlation_id or uuid.uuid4().hex[:12],
    )
