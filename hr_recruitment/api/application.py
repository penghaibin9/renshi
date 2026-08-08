"""
hr_recruitment/api/application.py

HR04-03 应聘申请 API。

  POST /api/hr/v1/recruitment/applications/drafts            保存草稿
  POST /api/hr/v1/recruitment/applications/{id}/submit       提交（幂等，Idempotency-Key）
  POST /api/hr/v1/recruitment/applications/{id}/withdraw     撤回
  GET  /api/hr/v1/recruitment/applications/{id}              详情（含 ledger）
  POST /api/hr/v1/recruitment/applications/{id}/materials    添加材料

硬规则：
- submit 幂等：重复调用返回原申请（Idempotency-Key / active 唯一约束兜底）。
- 状态迁移写 ledger。
- candidate self scope：候选人只能看本人（S5 公开门户）。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import (
    error,
    get_idempotency_key,
    make_hr04_context,
    ok,
)
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.services.application_service import (
    ApplicationService,
    ApplicationServiceError,
)


def _handle(request, exc):
    if isinstance(exc, (Hr04ApiError, ApplicationServiceError)):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_http_methods(["POST"])
def save_draft(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无操作申请权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = ApplicationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        app = service.save_draft(
            candidate_id=body.get("candidate_id"),
            recruitment_position_id=body.get("recruitment_position_id"),
            form_data=body.get("form_data"),
            application_id=body.get("application_id"),
        )
        return ok(request, {"id": str(app.id), "canonical_status": app.canonical_status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def submit_application(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无提交申请权限", 403)
    try:
        service = ApplicationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        app = service.submit(
            application_id=application_id,
            idempotency_key=get_idempotency_key(request),
        )
        return ok(
            request,
            {"id": str(app.id), "application_no": app.application_no, "canonical_status": app.canonical_status},
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def withdraw_application(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无撤回权限", 403)
    try:
        service = ApplicationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        app = service.withdraw(application_id=application_id)
        return ok(request, {"id": str(app.id), "canonical_status": app.canonical_status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def application_detail(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无查看申请权限", 403)
    from hr_recruitment.models import HrApplicationTransition, HrJobApplication

    try:
        app = HrJobApplication.objects.select_related("candidate_id", "recruitment_position_id").get(
            id=application_id, tenant_id=ctx.tenant_id
        )
    except HrJobApplication.DoesNotExist:
        return error(request, "APPLICATION_NOT_FOUND", "申请不存在", 404)
    transitions = HrApplicationTransition.objects.filter(
        tenant_id=ctx.tenant_id, application_id=app
    ).order_by("occurred_at")
    return ok(
        request,
        {
            "id": str(app.id),
            "application_no": app.application_no,
            "canonical_status": app.canonical_status,
            "workflow_stage_name": app.workflow_stage_name,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "candidate": {
                "id": str(app.candidate_id.id),
                "legal_name": app.candidate_id.legal_name,
            },
            "position": app.recruitment_position_id.post_catalog_name
            if app.recruitment_position_id
            else "",
            "announcement_version_id": str(app.announcement_version_id) if app.announcement_version_id else None,
            "qualification_rule_version_id": str(app.qualification_rule_version_id) if app.qualification_rule_version_id else None,
            "selection_scheme_version_id": str(app.selection_scheme_version_id) if app.selection_scheme_version_id else None,
            "transitions": [
                {
                    "from_status": t.from_status,
                    "to_status": t.to_status,
                    "action": t.action,
                    "actor_id": t.actor_id,
                    "occurred_at": t.occurred_at.isoformat(),
                }
                for t in transitions
            ],
        },
    )


@require_http_methods(["POST"])
def add_material(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无上传材料权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = ApplicationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        material = service.add_material(
            application_id=application_id,
            material_type=body.get("material_type", "OTHER"),
            title=body.get("title", ""),
            file_name=body.get("file_name", ""),
            file_path=body.get("file_path", ""),
            sha256=body.get("sha256", ""),
            mime_type=body.get("mime_type", ""),
            file_size_bytes=body.get("file_size_bytes", 0),
            sensitive_level=body.get("sensitive_level", "RESTRICTED_HR"),
        )
        return ok(
            request,
            {"id": str(material.id), "version_no": material.version_no},
            status=201,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
