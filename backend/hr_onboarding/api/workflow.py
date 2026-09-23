"""Authenticated task inbox and explicit completion commands; no CSRF bypass."""
from __future__ import annotations
import json

from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base
from hr_onboarding.api.exceptions import Hr05ApiError, PermissionDeniedError
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services.workflow_service import (
    OnboardingWorkflowService, workflow_summary, task_inbox, safe_case, find_assignees,
)


def command_data(request):
    if request.content_type == 'application/json':
        try:
            body = json.loads(request.body or b'{}')
        except (ValueError, UnicodeDecodeError):
            raise Hr05ApiError('请求内容不是有效的 JSON')
        if not isinstance(body, dict):
            raise Hr05ApiError('请求内容必须为对象')
    else:
        body = request.POST.dict()
    allowed = {'version', 'note', 'reason', 'evidence', 'username', 'fingerprint'}
    # Never accept a target tenant/actor/success/status from the client.
    if set(body) - allowed:
        raise Hr05ApiError('请求包含不支持的字段')
    version = request.headers.get('If-Match', '').strip('"') or body.pop('version', None)
    body.pop('version', None)
    return version, body


def run_task_command(request, task_id, action):
    try:
        ctx = base.make_hr05_context(request)
        version, data = command_data(request)
        response = OnboardingWorkflowService(tenant_id=ctx.tenant_id, user=request.user,
                    request_id=base._request_id(request)).task_command(
            task_id=task_id, action=action, version=version,
            idempotency_key=base.get_idempotency_key(request), data=data)
        return base.ok(request, response)
    except Hr05ApiError as exc:
        return base.handle_hr05_error(request, exc)


@require_GET
def inbox(request):
    try:
        ctx = base.make_hr05_context(request)
        try:
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('pageSize', 20))
        except (TypeError, ValueError):
            raise Hr05ApiError('分页参数必须为整数')
        state = request.GET.get('state', 'open')
        if state not in {'open', 'mine', 'unassigned', 'overdue', 'done'}:
            raise Hr05ApiError('不支持的任务筛选状态')
        return base.ok(request, task_inbox(tenant_id=ctx.tenant_id, user=request.user,
            keyword=request.GET.get('keyword', '')[:200].strip(), state=state, page=page, page_size=page_size, case_id=request.GET.get("case_id")))
    except Hr05ApiError as exc:
        return base.handle_hr05_error(request, exc)


@require_GET
@require_hr05_permission('hr05.case.view')
def summary(request, case_id):
    try:
        ctx = base.make_hr05_context(request)
        case = safe_case(ctx.tenant_id, case_id)
        return base.ok(request, workflow_summary(case, request.user))
    except Hr05ApiError as exc:
        return base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission('hr05.task.manage')
def assign(request, task_id):
    return run_task_command(request, task_id, 'assign')


def _case_command(request, case_id, action):
    try:
        ctx = base.make_hr05_context(request)
        version, data = command_data(request)
        result = OnboardingWorkflowService(tenant_id=ctx.tenant_id, user=request.user,
            request_id=base._request_id(request)).case_command(
                case_id=case_id, action=action, version=version,
                idempotency_key=base.get_idempotency_key(request), fingerprint=data.get('fingerprint', ''))
        return base.ok(request, result)
    except Hr05ApiError as exc:
        return base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission('hr05.task.manage')
def initialize(request, case_id):
    return _case_command(request, case_id, 'initialize')


@require_POST
@require_hr05_permission('hr05.case.activate')
def complete(request, case_id):
    return _case_command(request, case_id, 'complete')


@require_GET
@require_hr05_permission('hr05.task.manage')
def assignees(request):
    try:
        ctx = base.make_hr05_context(request)
        return base.ok(request, find_assignees(tenant_id=ctx.tenant_id, user=request.user,
            keyword=request.GET.get('keyword', '')))
    except Hr05ApiError as exc:
        return base.handle_hr05_error(request, exc)
