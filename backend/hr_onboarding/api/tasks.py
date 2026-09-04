"""
hr_onboarding/api/tasks.py

HR05-04 协同任务 + Provisioning API（总册 §14/§15）。
"""

from __future__ import annotations

from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.api.labels import (
    label_for,
    BLOCKING_LEVEL_LABELS,
    PROVISIONING_STATUS_LABELS,
    RESPONSIBLE_ROLE_LABELS,
    TASK_STATUS_LABELS,
)
from hr_onboarding.models import HrOnboardingCase, HrOnboardingTaskInstance, HrProvisioningRequest
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services.provisioning_service import ProvisioningService
from hr_onboarding.services.task_service import TaskService


def _load_case_or_404(context, case_id: str):
    try:
        case = HrOnboardingCase.objects.filter(tenant_id=context.tenant_id, id=case_id).first()
    except (ValueError, TypeError):
        case = None
    if case is None:
        raise NotFoundError("case 不存在或无权访问")
    return case


def _load_task_or_404(context, task_id: str):
    try:
        instance = HrOnboardingTaskInstance.objects.filter(
            tenant_id=context.tenant_id, id=task_id
        ).first()
    except (ValueError, TypeError):
        instance = None
    if instance is None:
        raise NotFoundError("任务不存在或无权访问")
    return instance


@require_GET
@require_hr05_permission("hr05.case.view")
def tasks_list(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        qs = HrOnboardingTaskInstance.objects.filter(case=case).select_related("definition")
        items = [
            {
                "id": str(t.id),
                "code": t.definition.code,
                "title": t.definition.title,
                "category": t.definition.category,
                "blocking_level": t.definition.blocking_level,
                "blockingLevelLabel": label_for(BLOCKING_LEVEL_LABELS, t.definition.blocking_level),
                "responsible_role": t.assignee_type,
                "responsibleRoleLabel": label_for(RESPONSIBLE_ROLE_LABELS, t.assignee_type),
                "assignee_id": t.assignee_id,
                "status": t.status,
                "statusLabel": label_for(TASK_STATUS_LABELS, t.status),
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in qs
        ]
        return api_base.ok(request, {"items": items, "total": len(items)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.task.complete")
def task_start(request, task_id: str):
    try:
        context = api_base.make_hr05_context(request)
        instance = _load_task_or_404(context, task_id)
        updated = TaskService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).start_task(instance)
        return api_base.ok(request, {"task_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.task.complete")
def task_complete(request, task_id: str):
    try:
        context = api_base.make_hr05_context(request)
        instance = _load_task_or_404(context, task_id)
        updated = TaskService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).complete_task(
            instance,
            note=request.POST.get("note", ""),
            evidence={"evidence": request.POST.get("evidence", "")},
        )
        return api_base.ok(request, {"task_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.task.waive")
def task_waive(request, task_id: str):
    try:
        context = api_base.make_hr05_context(request)
        instance = _load_task_or_404(context, task_id)
        updated = TaskService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).waive_task(instance, reason=request.POST.get("reason", ""))
        return api_base.ok(request, {"task_id": str(updated.id), "status": updated.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.identity.provision")
def provisioning_request(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        idem_key = api_base.get_idempotency_key(request)
        if not idem_key:
            raise Hr05ApiError("缺少 Idempotency-Key")
        target = request.POST.get("target_system")
        operation = request.POST.get("operation")
        if not target or not operation:
            raise Hr05ApiError("target_system/operation 必填")
        import json

        raw_payload = request.POST.get("payload", "{}")
        # 生产级：payload 大小限制（防恶意超大请求打爆内存/DB）
        if len(raw_payload) > 64 * 1024:
            raise Hr05ApiError("payload 超过 64KB 上限")
        try:
            payload = json.loads(raw_payload)
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            raise Hr05ApiError("payload 必须是 JSON 对象")
        req = ProvisioningService(tenant_id=context.tenant_id).request_provisioning(
            case,
            target_system=target,
            operation=operation,
            payload_version="v1",
            payload=payload,
            idempotency_key=idem_key,
        )
        return api_base.ok(
            request, {"provisioning_id": str(req.id), "status": req.status,
                      "statusLabel": label_for(PROVISIONING_STATUS_LABELS, req.status)}
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.identity.provision")
def provisioning_retry(request, provisioning_id: str):
    try:
        context = api_base.make_hr05_context(request)
        try:
            req = HrProvisioningRequest.objects.filter(
                tenant_id=context.tenant_id, id=provisioning_id
            ).first()
        except (ValueError, TypeError):
            req = None
        if req is None:
            raise NotFoundError("provisioning 不存在")
        svc = ProvisioningService(tenant_id=context.tenant_id)
        updated = svc.mark_running(req)
        return api_base.ok(request, {"provisioning_id": str(updated.id), "status": updated.status,
                                     "statusLabel": label_for(PROVISIONING_STATUS_LABELS, updated.status)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
