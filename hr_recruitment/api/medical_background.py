"""
hr_recruitment/api/medical_background.py

体检/考察 API（§12.8 / §39）。

  POST .../applications/{id}/medical        记录体检结论（result）
  GET  .../applications/{id}/medical        普通管理员只看结论摘要
  POST .../applications/{id}/background     记录考察/政审结论
  GET  .../applications/{id}/background     只看结论摘要

敏感隔离：sensitive_material_id 不返回到普通管理员视图；查看敏感材料走审计。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods

from hr_recruitment.api.base import error, make_hr04_context, ok
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.services.medical_background_service import (
    MedicalBackgroundService,
    MedicalBackgroundServiceError,
)


def _handle(request, exc):
    from django.core.exceptions import ObjectDoesNotExist

    if isinstance(exc, json.JSONDecodeError):
        return error(request, "INVALID_JSON", "请求体不是有效 JSON", 400)
    if isinstance(exc, ObjectDoesNotExist):
        return error(request, "NOT_FOUND", "资源不存在", 404)
    if isinstance(exc, (Hr04ApiError, MedicalBackgroundServiceError)):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


def _service(request):
    ctx = make_hr04_context(request)
    return MedicalBackgroundService(tenant_id=ctx.tenant_id, actor=str(request.user.id)), ctx


@require_http_methods(["POST"])
def record_medical(request, application_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.manage")):
        return error(request, "PERMISSION_DENIED", "无记录体检结论权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        check = service.record_medical(
            application_id=application_id,
            result=body.get("result"),
            scheduled_at=body.get("scheduled_at"),
            sensitive_material_id=body.get("sensitive_material_id"),
            verified_by=body.get("verified_by", ""),
        )
        return ok(request, {"id": str(check.id), "result": check.result})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def medical_summary(request, application_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.manage")):
        return error(request, "PERMISSION_DENIED", "无查看体检权限", 403)
    try:
        data = service.get_medical_summary(application_id=application_id)
        return ok(request, data or {"result": None})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def record_background(request, application_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.manage")):
        return error(request, "PERMISSION_DENIED", "无记录考察结论权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        check = service.record_background(
            application_id=application_id,
            result=body.get("result"),
            summary=body.get("summary", ""),
            sensitive_material_id=body.get("sensitive_material_id"),
            verified_by=body.get("verified_by", ""),
        )
        return ok(request, {"id": str(check.id), "result": check.result})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def background_summary(request, application_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.manage")):
        return error(request, "PERMISSION_DENIED", "无查看考察权限", 403)
    try:
        data = service.get_background_summary(application_id=application_id)
        return ok(request, data or {"result": None})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
