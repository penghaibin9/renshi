"""
Reliable HR05 transactional-outbox dispatcher.

Events remain PENDING until an explicitly registered handler returns a typed
acknowledgement with a stable external receipt. Workers claim rows with a
database lease, retry failures with exponential backoff, and move exhausted
events to the existing FAILED state.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Protocol

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from hr_onboarding.models import HrOnboardingOutboxEvent

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 10
BATCH_SIZE = 100
LEASE_SECONDS = 120
BASE_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 60 * 60


@dataclass(frozen=True)
class OutboxEnvelope:
    """Immutable provider input; ``event_id`` is the downstream idempotency key."""

    event_id: str
    event_type: str
    event_version: int
    tenant_id: int
    aggregate_type: str
    aggregate_id: str
    correlation_id: str
    occurred_at: datetime
    payload: Mapping[str, Any]

    @classmethod
    def from_event(cls, event: HrOnboardingOutboxEvent) -> "OutboxEnvelope":
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            tenant_id=event.tenant_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            correlation_id=event.correlation_id,
            occurred_at=event.occurred_at,
            payload=dict(event.payload_json or {}),
        )


@dataclass(frozen=True)
class DispatchResult:
    """Typed handler outcome. Truthy values alone are never acknowledgements."""

    acknowledged: bool
    external_ref: str = ""
    error: str = ""

    @classmethod
    def ack(cls, external_ref: str) -> "DispatchResult":
        return cls(acknowledged=True, external_ref=str(external_ref or "").strip())

    @classmethod
    def retry(cls, error: str) -> "DispatchResult":
        return cls(acknowledged=False, error=str(error or "").strip())


class OutboxHandler(Protocol):
    def deliver(self, envelope: OutboxEnvelope) -> DispatchResult: ...


Handler = OutboxHandler | Callable[[OutboxEnvelope], DispatchResult]


class OutboxHandlerRegistry:
    """Explicit event-type to provider registry; missing handlers fail closed."""

    def __init__(self):
        self._handlers: dict[str, Handler] = {}

    def register(self, event_type: str, handler: Handler, *, replace: bool = False):
        event_type = str(event_type or "").strip()
        if not event_type:
            raise ValueError("event_type is required")
        if not callable(handler) and not callable(getattr(handler, "deliver", None)):
            raise TypeError("handler must be callable or expose deliver(envelope)")
        if event_type in self._handlers and not replace:
            raise ValueError(f"handler already registered for {event_type}")
        self._handlers[event_type] = handler
        return handler

    def resolve(self, event_type: str) -> Handler | None:
        return self._handlers.get(event_type)


default_handler_registry = OutboxHandlerRegistry()


def register_handler(event_type: str, *, replace: bool = False):
    """Decorator used by deploy-time integration modules to register providers."""

    def decorator(handler: Handler):
        default_handler_registry.register(event_type, handler, replace=replace)
        return handler

    return decorator


def _eligible(qs, now: datetime):
    return qs.filter(status=HrOnboardingOutboxEvent.Status.PENDING).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
        Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
    )


def _claim_batch(
    *,
    tenant_id: int | None,
    limit: int,
    worker_id: str,
    now: datetime,
    lease_seconds: int = LEASE_SECONDS,
) -> list:
    """Atomically lease due rows; expired leases are eligible for recovery."""
    worker_id = str(worker_id or "").strip()
    if not worker_id:
        raise ValueError("worker_id is required")
    if len(worker_id) > 64:
        raise ValueError("worker_id must be at most 64 characters")
    if limit <= 0:
        return []

    lease_until = now + timedelta(seconds=max(1, lease_seconds))
    with transaction.atomic():
        candidates = HrOnboardingOutboxEvent.objects.all()
        if tenant_id is not None:
            candidates = candidates.filter(tenant_id=tenant_id)
        candidates = _eligible(candidates, now).order_by("occurred_at", "id")
        if connection.features.has_select_for_update:
            lock_kwargs = {}
            if connection.features.has_select_for_update_skip_locked:
                lock_kwargs["skip_locked"] = True
            candidates = candidates.select_for_update(**lock_kwargs)
        candidate_ids = list(candidates.values_list("id", flat=True)[:limit])

        claimed = []
        for event_id in candidate_ids:
            # Conditional UPDATE is also the claim CAS on engines without
            # SELECT ... FOR UPDATE SKIP LOCKED (including isolated SQLite tests).
            claimable = _eligible(
                HrOnboardingOutboxEvent.objects.filter(id=event_id), now
            )
            updated = claimable.update(
                lease_owner=worker_id,
                lease_expires_at=lease_until,
            )
            if updated == 1:
                claimed.append(event_id)
        return claimed


def _invoke_handler(handler: Handler, envelope: OutboxEnvelope) -> DispatchResult:
    deliver = getattr(handler, "deliver", None)
    result = deliver(envelope) if callable(deliver) else handler(envelope)
    if not isinstance(result, DispatchResult):
        raise TypeError("HR05_OUTBOX_INVALID_HANDLER_RESULT")
    if result.acknowledged and not result.external_ref:
        raise ValueError("HR05_OUTBOX_ACK_RECEIPT_REQUIRED")
    return result


def _retry_delay(attempts: int) -> timedelta:
    seconds = min(
        BASE_RETRY_SECONDS * (2 ** max(0, attempts - 1)),
        MAX_RETRY_SECONDS,
    )
    return timedelta(seconds=seconds)


def _record_outcome(
    *,
    event_id,
    worker_id: str,
    now: datetime,
    result: DispatchResult | None = None,
    error: str = "",
) -> str:
    """Finalize one owned lease. A reclaimed lease cannot be overwritten."""
    with transaction.atomic():
        event = (
            HrOnboardingOutboxEvent.objects.select_for_update()
            .filter(
                id=event_id,
                status=HrOnboardingOutboxEvent.Status.PENDING,
                lease_owner=worker_id,
            )
            .first()
        )
        if event is None:
            return "lost"

        event.attempts += 1
        event.last_attempt_at = now
        event.lease_owner = ""
        event.lease_expires_at = None

        if result is not None and result.acknowledged and result.external_ref:
            event.status = HrOnboardingOutboxEvent.Status.SENT
            event.external_ref = result.external_ref[:255]
            event.sent_at = now
            event.next_attempt_at = None
            event.last_error = ""
            outcome = "sent"
        else:
            failure = error or (result.error if result is not None else "")
            event.last_error = (failure or "HR05_OUTBOX_HANDLER_RETRY")[:2000]
            event.sent_at = None
            if event.attempts >= MAX_ATTEMPTS:
                event.status = HrOnboardingOutboxEvent.Status.FAILED
                event.next_attempt_at = None
                outcome = "failed"
            else:
                event.status = HrOnboardingOutboxEvent.Status.PENDING
                event.next_attempt_at = now + _retry_delay(event.attempts)
                outcome = "retrying"

        event.save(
            update_fields=[
                "status",
                "attempts",
                "last_error",
                "next_attempt_at",
                "last_attempt_at",
                "lease_owner",
                "lease_expires_at",
                "external_ref",
                "sent_at",
            ]
        )
        return outcome


def _dispatch_claimed(
    *,
    event_id,
    worker_id: str,
    registry: OutboxHandlerRegistry,
    now: datetime,
) -> str:
    event = (
        HrOnboardingOutboxEvent.objects.filter(
            id=event_id,
            status=HrOnboardingOutboxEvent.Status.PENDING,
            lease_owner=worker_id,
        )
        .first()
    )
    if event is None:
        return "lost"

    handler = registry.resolve(event.event_type)
    if handler is None:
        return _record_outcome(
            event_id=event.id,
            worker_id=worker_id,
            now=now,
            error=f"HR05_OUTBOX_HANDLER_NOT_REGISTERED:{event.event_type}",
        )

    try:
        result = _invoke_handler(handler, OutboxEnvelope.from_event(event))
    except Exception as exc:
        logger.exception(
            "HR05 outbox handler failed event_id=%s event_type=%s",
            event.event_id,
            event.event_type,
        )
        return _record_outcome(
            event_id=event.id,
            worker_id=worker_id,
            now=now,
            error=f"HR05_OUTBOX_HANDLER_ERROR:{type(exc).__name__}:{exc}",
        )

    return _record_outcome(
        event_id=event.id,
        worker_id=worker_id,
        now=now,
        result=result,
    )


def dispatch_pending(
    *,
    tenant_id: int | None = None,
    limit: int = BATCH_SIZE,
    registry: OutboxHandlerRegistry | None = None,
    worker_id: str | None = None,
    now: datetime | None = None,
    lease_seconds: int = LEASE_SECONDS,
) -> dict:
    """Claim and deliver one batch. The default registry is intentionally empty."""
    registry = registry if registry is not None else default_handler_registry
    worker_id = worker_id or uuid.uuid4().hex
    stats = {
        "dispatched": 0,
        "retrying": 0,
        "failed": 0,
        "lost": 0,
        "total": 0,
    }
    # Claim immediately before delivery instead of leasing a large queue whose
    # tail could expire while earlier network calls are still running.
    for _ in range(max(0, limit)):
        cycle_now = now or timezone.now()
        claimed = _claim_batch(
            tenant_id=tenant_id,
            limit=1,
            worker_id=worker_id,
            now=cycle_now,
            lease_seconds=lease_seconds,
        )
        if not claimed:
            break
        event_id = claimed[0]
        stats["total"] += 1
        outcome = _dispatch_claimed(
            event_id=event_id,
            worker_id=worker_id,
            registry=registry,
            now=cycle_now,
        )
        key = "dispatched" if outcome == "sent" else outcome
        stats[key] += 1
    return stats
