"""
hr_recruitment/api/qualification.py

HR04-04 资格审查 API（总册 11）。

  GET  /api/hr/v1/recruitment/qualification/workbench          审核工作台（队列/统计）
  GET  /api/hr/v1/recruitment/qualification/applications/{id}/precheck   系统预检（只建议）
  POST /api/hr/v1/recruitment/qualification/applications/{id}/start-review
  POST /api/hr/v1/recruitment/qualification/applications/{id}/decision   {decision, reason_*}
  POST /api/hr/v1/recruitment/qualification/rule-sets           创建规则集
  POST /api/hr/v1/recruitment/qualification/rule-sets/{id}/rules 添加规则
  POST /api/hr/v1/recruitment/qualification/rule-sets/{id}/lock 锁定（不可变）

硬规则：系统预检只建议不终审；DISQUALIFIED 必须记录原因；规则集锁定后不可改。
"""

from __future__ import annotations

import json

from django.db.models import Count, Q
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import error, make_hr04_context, ok
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.models import HrJobApplication
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.services.qualification_service import (
    QualificationService,
    QualificationServiceError,
)


def _handle(request, exc):
    if isinstance(exc, (Hr04ApiError, QualificationServiceError)):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def workbench(request):
    """审核工作台：按岗位统计待审/已审/退回/不合格（总册 11.1）。"""
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.review")):
        return error(request, "PERMISSION_DENIED", "无资格审查权限", 403)
    position_id = request.GET.get("position_id")
    qs = HrJobApplication.objects.filter(tenant_id=ctx.tenant_id)
    if position_id:
        qs = qs.filter(recruitment_position_id_id=position_id)
    stats = {
        "pending": qs.filter(
            canonical_status__in=[S.SUBMITTED, S.UNDER_REVIEW, S.RESUBMITTED]
        ).count(),
        "qualified": qs.filter(canonical_status=S.QUALIFIED).count(),
        "returned": qs.filter(canonical_status=S.RETURNED).count(),
        "disqualified": qs.filter(canonical_status=S.DISQUALIFIED).count(),
        "total": qs.count(),
    }
    queue = (
        qs.filter(canonical_status__in=[S.SUBMITTED, S.UNDER_REVIEW, S.RESUBMITTED])
        .select_related("candidate_id", "recruitment_position_id")
        .order_by("submitted_at")[:50]
    )
    return ok(
        request,
        {
            "stats": stats,
            "queue": [
                {
                    "id": str(a.id),
                    "application_no": a.application_no,
                    "candidate_name": a.candidate_id.legal_name if a.candidate_id else "",
                    "position": a.recruitment_position_id.post_catalog_name if a.recruitment_position_id else "",
                    "canonical_status": a.canonical_status,
                    "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                }
                for a in queue
            ],
        },
    )


@require_GET
def precheck(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.review")):
        return error(request, "PERMISSION_DENIED", "无资格审查权限", 403)
    try:
        service = QualificationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        return ok(request, service.run_precheck(application_id=application_id))
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def start_review(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.review")):
        return error(request, "PERMISSION_DENIED", "无资格审查权限", 403)
    try:
        service = QualificationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        app = service.start_review(application_id=application_id)
        return ok(request, {"id": str(app.id), "canonical_status": app.canonical_status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def decision(request, application_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.finalize")):
        return error(request, "PERMISSION_DENIED", "无资格审查最终结论权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = QualificationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        app = service.decision(
            application_id=application_id,
            decision=body.get("decision"),
            reason_code=body.get("reason_code", ""),
            reason_text=body.get("reason_text", ""),
            missing_items=body.get("missing_items"),
        )
        return ok(request, {"id": str(app.id), "canonical_status": app.canonical_status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_rule_set(request):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.finalize")):
        return error(request, "PERMISSION_DENIED", "无资格规则配置权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = QualificationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        rs = service.create_rule_set(position_id=body.get("position_id"))
        return ok(request, {"id": str(rs.id), "version_no": rs.version_no}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def add_rule(request, rule_set_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.finalize")):
        return error(request, "PERMISSION_DENIED", "无资格规则配置权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        service = QualificationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        rule = service.add_rule(
            rule_set_version_id=rule_set_id,
            rule_code=body.get("rule_code"),
            label=body.get("label"),
            rule_type=body.get("rule_type", ""),
            operator=body.get("operator", "eq"),
            expected_value=body.get("expected_value"),
            severity=body.get("severity", "SOFT"),
            evidence_requirement=body.get("evidence_requirement", ""),
            sequence=body.get("sequence", 0),
        )
        return ok(request, {"id": str(rule.id), "rule_code": rule.rule_code}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def lock_rule_set(request, rule_set_id):
    try:
        ctx = make_hr04_context(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.qualification.finalize")):
        return error(request, "PERMISSION_DENIED", "无资格规则配置权限", 403)
    try:
        service = QualificationService(tenant_id=ctx.tenant_id, actor=str(request.user.id))
        rs = service.lock_rule_set(rule_set_version_id=rule_set_id)
        return ok(request, {"id": str(rs.id), "status": rs.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
