"""Production HTTP adapters for HR16 external exit participants.

The saga owns retry/lease state.  These adapters perform one bounded network
call and return a durable, secret-free receipt.  Missing deployment credentials
are an explicit retryable UNAVAILABLE result, never a fabricated success.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib import error, request
from urllib.parse import urlparse

from django.conf import settings


def _configuration(participant: str) -> tuple[str, str, float]:
    configured = getattr(settings, "HR16_EXIT_EXTERNAL_PROVIDERS", {}) or {}
    item = configured.get(participant, {}) if isinstance(configured, Mapping) else {}
    if not isinstance(item, Mapping):
        item = {}
    url = str(item.get("url", "") or "").strip()
    token = str(item.get("token", "") or "").strip()
    try:
        timeout = float(item.get("timeoutSeconds", 10))
    except (TypeError, ValueError):
        timeout = 10.0
    return url, token, max(1.0, min(timeout, 30.0))


def _payload(*, participant, tenant_id, case, effect, actor_user_id):
    return {
        "schemaVersion": "hr16.exit-participant.request.1",
        "participant": participant,
        "tenantId": int(tenant_id),
        "actorUserId": actor_user_id,
        "idempotencyKey": effect.idempotency_key,
        "correlationId": effect.correlation_id,
        "effectId": str(effect.id),
        "effectVersion": effect.effect_version,
        "case": {
            "id": str(case.id),
            "caseNo": case.case_no,
            "personId": str(case.person_id),
            "employmentRelationshipId": str(case.employment_relationship_id),
            "exitType": case.exit_type,
            "plannedEmploymentEndDate": (
                case.planned_employment_end_date.isoformat()
                if case.planned_employment_end_date
                else None
            ),
            "plannedAccessEndAt": (
                case.planned_access_end_at.isoformat()
                if case.planned_access_end_at
                else None
            ),
        },
    }


def _execute(participant: str, *, tenant_id, case, effect, actor_user_id=None):
    # Local import avoids a module cycle with participant_service's provider loader.
    from hr_exit.services.participant_service import ExitParticipantUnavailable

    url, token, timeout = _configuration(participant)
    if not url or not token:
        raise ExitParticipantUnavailable(
            f"{participant} provider URL/token is not configured"
        )
    parsed = urlparse(url)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not parsed.hostname
        or parsed.scheme not in {"http", "https"}
        or (parsed.scheme != "https" and not (settings.DEBUG and loopback))
    ):
        raise ExitParticipantUnavailable(
            f"{participant} provider must use HTTPS (HTTP loopback is development-only)"
        )

    body = json.dumps(
        _payload(
            participant=participant,
            tenant_id=tenant_id,
            case=case,
            effect=effect,
            actor_user_id=actor_user_id,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    outbound = request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Idempotency-Key": effect.idempotency_key,
            "X-Correlation-Id": effect.correlation_id or str(effect.id),
        },
    )
    try:
        # Scheme and production HTTPS enforcement are validated immediately
        # above; custom/file schemes cannot reach this call.
        with request.urlopen(outbound, timeout=timeout) as response:  # nosec B310
            raw = response.read()
    except error.HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
            raise ExitParticipantUnavailable(
                f"{participant} provider temporarily unavailable (HTTP {exc.code})"
            ) from exc
        raise RuntimeError(
            f"{participant} provider rejected exit effect (HTTP {exc.code})"
        ) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise ExitParticipantUnavailable(
            f"{participant} provider connection unavailable"
        ) from exc

    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{participant} provider returned invalid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise RuntimeError(f"{participant} provider response must be a JSON object")

    receipt = decoded.get("receipt", decoded)
    if not isinstance(receipt, Mapping):
        raise RuntimeError(f"{participant} provider receipt must be an object")
    receipt_id = str(receipt.get("receiptId", "") or "").strip()
    if not receipt_id:
        raise RuntimeError(f"{participant} provider receiptId is required")
    replay_key = str(receipt.get("idempotencyKey", "") or "").strip()
    if replay_key and replay_key != effect.idempotency_key:
        raise RuntimeError(f"{participant} provider idempotency receipt mismatch")

    return {
        "provider": f"hr16-{participant.lower()}-http",
        "participant": participant,
        "receiptId": receipt_id,
        "idempotencyKey": effect.idempotency_key,
        "receipt": dict(receipt),
    }


def iam_participant_provider(**kwargs):
    return _execute("IAM", **kwargs)


def asset_participant_provider(**kwargs):
    return _execute("ASSET", **kwargs)


def finance_participant_provider(**kwargs):
    return _execute("FINANCE", **kwargs)
