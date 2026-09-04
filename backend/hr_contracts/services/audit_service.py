"""Append-only HR07 domain audit helpers."""

from __future__ import annotations


def record(
    *,
    tenant_id,
    action,
    object_type,
    object_id,
    actor_id=None,
    purpose="",
    before=None,
    after=None,
    request_id="",
):
    from hr_contracts.models import HrContractAuditEvent

    return HrContractAuditEvent.objects.create(
        tenant_id=tenant_id,
        action=str(action)[:64],
        object_type=str(object_type)[:64],
        object_id=str(object_id)[:128],
        actor_id=actor_id,
        purpose=str(purpose or "")[:300],
        before_json=before or {},
        after_json=after or {},
        request_id=str(request_id or "")[:128],
    )


def record_sensitive_access(
    *, tenant_id, agreement_id, document_id, actor_id, action, purpose, request_id=""
):
    return record(
        tenant_id=tenant_id,
        action=f"document.{str(action).lower()}",
        object_type="CONTRACT_DOCUMENT",
        object_id=document_id,
        actor_id=actor_id,
        purpose=purpose,
        after={"agreementId": str(agreement_id)},
        request_id=request_id,
    )
