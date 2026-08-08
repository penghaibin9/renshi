"""
hr_recruitment/api/assessment.py

HR04-05 考试面试与考察 API（总册 12）。

  POST /api/hr/v1/recruitment/assessment/schemes               创建评分方案
  POST /api/hr/v1/recruitment/assessment/schemes/{id}/components 添加组件
  POST /api/hr/v1/recruitment/assessment/schemes/{id}/lock     锁定方案
  POST /api/hr/v1/recruitment/assessment/events                创建场次
  POST /api/hr/v1/recruitment/assessment/events/{id}/evaluators 分配专家
  POST /api/hr/v1/recruitment/assessment/assignments/{id}/conflict 声明冲突
  POST /api/hr/v1/recruitment/assessment/score-sheets           创建评分表
  GET  /api/hr/v1/recruitment/assessment/score-sheets/{id}      评分上下文（盲评裁剪）
  POST /api/hr/v1/recruitment/assessment/score-sheets/{id}/scores 保存/提交评分
  POST /api/hr/v1/recruitment/assessment/score-sheets/{id}/lock 锁定
  POST /api/hr/v1/recruitment/assessment/score-sheets/{id}/reopen 解锁（特权）
  POST /api/hr/v1/recruitment/assessment/positions/{id}/freeze-result 冻结结果快照

硬规则：总分服务端计算；锁定后不可改；解锁特权+reason；盲评服务端裁剪。
"""

from __future__ import annotations

import json

from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import error, make_hr04_context, ok
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.permissions import require_hr04_permission
from hr_recruitment.services.assessment_service import (
    AssessmentService,
    AssessmentServiceError,
)


def _handle(request, exc):
    if isinstance(exc, (Hr04ApiError, AssessmentServiceError)):
        return error(request, exc.code, exc.message, getattr(exc, "http_status", exc.status_code if hasattr(exc, "status_code") else 422))
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


def _service(request):
    ctx = make_hr04_context(request)
    return AssessmentService(tenant_id=ctx.tenant_id, actor=str(request.user.id)), ctx


def _perm(request, code, msg):
    if not (request.user.is_superuser or request.user.has_perm(code)):
        return error(request, "PERMISSION_DENIED", msg, 403)
    return None


@require_http_methods(["POST"])
def create_scheme(request):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无配置评分方案权限")
    if denied:
        return denied
    try:
        body = json.loads(request.body or b"{}")
        scheme = service.create_scheme(position_id=body.get("position_id"))
        return ok(request, {"id": str(scheme.id), "version_no": scheme.version_no}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def add_component(request, scheme_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无配置评分方案权限")
    if denied:
        return denied
    try:
        body = json.loads(request.body or b"{}")
        comp = service.add_component(
            scheme_version_id=scheme_id,
            component_type=body.get("component_type"),
            name=body.get("name"),
            weight=body.get("weight"),
            max_score=body.get("max_score", 100),
            pass_score=body.get("pass_score"),
            sequence=body.get("sequence", 0),
            is_elimination=body.get("is_elimination", False),
        )
        return ok(request, {"id": str(comp.id), "name": comp.name}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def lock_scheme(request, scheme_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无配置评分方案权限")
    if denied:
        return denied
    try:
        scheme = service.lock_scheme(scheme_version_id=scheme_id)
        return ok(request, {"id": str(scheme.id), "status": scheme.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_event(request):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无创建场次权限")
    if denied:
        return denied
    try:
        body = json.loads(request.body or b"{}")
        event = service.create_event(
            component_id=body.get("component_id"),
            title=body.get("title"),
            event_date=body.get("event_date"),
            start_time=body.get("start_time"),
            end_time=body.get("end_time"),
            mode=body.get("mode", "ONSITE"),
            location=body.get("location", ""),
            capacity=body.get("capacity", 0),
        )
        return ok(request, {"id": str(event.id)}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def assign_evaluator(request, event_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无分配专家权限")
    if denied:
        return denied
    try:
        body = json.loads(request.body or b"{}")
        assignment = service.assign_evaluator(
            event_id=event_id,
            evaluator_staff_id=body.get("evaluator_staff_id"),
            role=body.get("role", ""),
            blind_mode=body.get("blind_mode", False),
        )
        return ok(request, {"id": str(assignment.id)}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def declare_conflict(request, assignment_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无回避管理权限")
    if denied:
        return denied
    try:
        body = json.loads(request.body or b"{}")
        assignment = service.declare_conflict(
            assignment_id=assignment_id,
            status=body.get("status"),
            recusal_reason=body.get("recusal_reason", ""),
        )
        return ok(request, {"id": str(assignment.id), "conflict_status": assignment.conflict_status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def create_score_sheet(request):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无创建评分表权限")
    if denied:
        return denied
    try:
        body = json.loads(request.body or b"{}")
        sheet = service.create_score_sheet(
            application_id=body.get("application_id"),
            event_id=body.get("event_id"),
            evaluator_id=body.get("evaluator_id"),
        )
        return ok(request, {"id": str(sheet.id), "status": sheet.status}, status=201)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_GET
def score_sheet_detail(request, score_sheet_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.score")):
        return error(request, "PERMISSION_DENIED", "无评分权限", 403)
    try:
        blind = request.GET.get("blind") == "true"
        return ok(request, service.get_score_sheet_context(score_sheet_id=score_sheet_id, blind=blind))
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def save_scores(request, score_sheet_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.score")):
        return error(request, "PERMISSION_DENIED", "无评分权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        sheet = service.save_scores(
            score_sheet_id=score_sheet_id,
            scores=body.get("scores", {}),
            submit=body.get("submit", False),
        )
        return ok(
            request,
            {
                "id": str(sheet.id),
                "status": sheet.status,
                "total_score": str(sheet.total_score),  # 服务端计算
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def lock_score_sheet(request, score_sheet_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无锁定评分权限")
    if denied:
        return denied
    try:
        sheet = service.lock_score_sheet(score_sheet_id=score_sheet_id)
        return ok(request, {"id": str(sheet.id), "status": sheet.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_http_methods(["POST"])
def reopen_score_sheet(request, score_sheet_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    if not (request.user.is_superuser or request.user.has_perm("hr04.assessment.unlock_score")):
        return error(request, "PERMISSION_DENIED", "无评分解锁权限", 403)
    try:
        body = json.loads(request.body or b"{}")
        sheet = service.reopen_score_sheet(
            score_sheet_id=score_sheet_id,
            reason=body.get("reason", ""),
            approve=body.get("approve", False),
            approving_user=body.get("approving_user", ""),
        )
        return ok(request, {"id": str(sheet.id), "status": sheet.status})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@require_POST
def freeze_result(request, position_id):
    try:
        service, ctx = _service(request)
    except Hr04ApiError as exc:
        return error(request, exc.code, exc.message, exc.status_code)
    denied = _perm(request, "hr04.assessment.manage", "无冻结结果权限")
    if denied:
        return denied
    try:
        snapshots = service.freeze_result_snapshot(position_id=position_id)
        return ok(
            request,
            {
                "count": len(snapshots),
                "snapshots": [
                    {
                        "rank": s.rank,
                        "application_id": str(s.application_id_id),
                        "final_score": str(s.final_score),
                    }
                    for s in snapshots
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
