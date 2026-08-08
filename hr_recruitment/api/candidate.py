"""
hr_recruitment/api/candidate.py

HR04-03 人才库 API（总册 23）。

  GET  /api/hr/v1/recruitment/candidates                人才库列表
  GET  /api/hr/v1/recruitment/candidates/{candidateId}  候选人详情（含应聘记录）
  POST /api/hr/v1/recruitment/candidates/identity-match 去重匹配（EXACT/POSSIBLE/NO_MATCH/INSUFFICIENT_DATA）
  POST /api/hr/v1/recruitment/candidates/identity-match-exact  高敏 exact search（特权）
  POST /api/hr/v1/recruitment/candidates                创建候选

硬规则：
- 普通模糊搜索不包含身份证/简历正文。
- identity-match-exact 仅特权（hr04.application.sensitive_view）。
- 敏感字段服务端裁剪（privacy.py）。
- 绝不自动 merge。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import error, make_hr04_context, ok
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.selectors import candidate as candidate_selector
from hr_recruitment.services.candidate_service import CandidateService, CandidateServiceError


def _handle(request, exc):
    if isinstance(exc, (Hr04ApiError, CandidateServiceError)):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def list_candidates(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无查看人才库权限", 403)
    try:
        return ok(
            request,
            candidate_selector.list_candidates(
                tenant_id=ctx.tenant_id,
                keyword=request.GET.get("keyword"),
                status=request.GET.get("status"),
                source=request.GET.get("source"),
                page=int(request.GET.get("page", 1)),
                page_size=int(request.GET.get("page_size", 20)),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def candidate_detail(request, candidate_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无查看人才库权限", 403)
    data = candidate_selector.get_candidate(tenant_id=ctx.tenant_id, candidate_id=candidate_id)
    if data is None:
        return error(request, "CANDIDATE_NOT_FOUND", "候选人不存在", 404)
    return ok(request, data)


@require_http_methods(["POST"])
def create_candidate(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无创建候选人权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = CandidateService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        candidate = service.create_candidate(
            legal_name=body.get("legal_name"),
            preferred_name=body.get("preferred_name", ""),
            primary_email=body.get("primary_email", ""),
            primary_mobile=body.get("primary_mobile", ""),
            national_id=body.get("national_id"),
            source=body.get("source", "ADMIN_CREATED"),
            talent_tags=body.get("talent_tags"),
        )
        return ok(request, {"id": str(candidate.id), "candidate_uid": candidate.candidate_uid}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def identity_match(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.application.view")):
        return error(request, "PERMISSION_DENIED", "无身份匹配权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = CandidateService(tenant_id=ctx.tenant_id)
        result = service.identity_match(
            legal_name=body.get("legal_name"),
            primary_email=body.get("primary_email"),
            primary_mobile=body.get("primary_mobile"),
            national_id=body.get("national_id"),
        )
        return ok(request, result)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def identity_match_exact(request):
    """高敏 exact search（身份证 tenant-scoped hash）：仅特权用户（总册 23）。"""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (
        request.user.is_superuser or request.user.has_perm("hr04.application.sensitive_view")
    ):
        return error(request, "PERMISSION_DENIED", "无高敏身份匹配权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        national_id = body.get("national_id")
        if not national_id:
            return error(request, "INVALID_REQUEST", "缺少身份证号", 422)
        service = CandidateService(tenant_id=ctx.tenant_id)
        result = service.identity_match(national_id=national_id)
        return ok(request, result)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
