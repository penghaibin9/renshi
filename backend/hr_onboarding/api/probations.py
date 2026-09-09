"""
hr_onboarding/api/probations.py

HR05-05 试用与转正 API（总册 §17.7）。
"""

from __future__ import annotations

import json

from django.db import transaction
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError, VersionConflictError
from hr_onboarding.api.labels import (
    label_for,
    PROBATION_RESULT_LABELS,
    PROBATION_STATUS_LABELS,
)
from hr_onboarding.models import HrProbationCase
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services.probation_service import ProbationService


def _load_probation_or_404(context, probation_id: str, *, for_update: bool = False):
    try:
        qs = HrProbationCase.objects.filter(tenant_id=context.tenant_id, id=probation_id)
        probation = (qs.select_for_update() if for_update else qs).first()
    except (ValueError, TypeError):
        probation = None
    if probation is None:
        raise NotFoundError("试用记录不存在或无权访问")
    return probation


def _parse_date(value):
    from django.utils.dateparse import parse_date

    if not value:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise Hr05ApiError("日期格式非法")
    return parsed


def _payload(request):
    """兼容既有表单写入，并支持统一前端客户端的 JSON body。"""
    content_type = (request.content_type or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return request.POST
    try:
        raw = request.body.decode(request.encoding or "utf-8") if request.body else "{}"
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Hr05ApiError("请求内容不是有效 JSON") from exc
    if not isinstance(data, dict):
        raise Hr05ApiError("请求内容必须是对象")
    return data


def _required_text(payload, key: str, label: str, *, max_length: int = 2000) -> str:
    value = str(payload.get(key, "") or "").strip()
    if not value:
        raise Hr05ApiError(f"{label}必填")
    if len(value) > max_length:
        raise Hr05ApiError(f"{label}不能超过 {max_length} 个字符")
    return value


def _check_expected_version(request, payload, probation) -> None:
    """在调用方持有行锁时校验 If-Match/version，避免旧页面覆盖新状态。"""
    raw = api_base.get_if_match(request)
    if raw in (None, ""):
        raw = payload.get("version")
    if raw in (None, ""):
        return
    text = str(raw).strip()
    if text.startswith("W/"):
        text = text[2:].strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    if not text.isascii() or not text.isdigit():
        raise Hr05ApiError("If-Match/version 必须是整数")
    expected = int(text)
    if expected != probation.version:
        raise VersionConflictError(
            "试用记录已被其他操作更新，请刷新后重试",
            details={"expectedVersion": expected, "currentVersion": probation.version},
        )


@require_GET
@require_hr05_permission("hr05.probation.manage")
def probations_list(request):
    try:
        context = api_base.make_hr05_context(request)
        qs = HrProbationCase.objects.filter(tenant_id=context.tenant_id)
        status = request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        items = [
            {
                "id": str(p.id),
                "staff_master_id": str(p.staff_master_id) if p.staff_master_id else None,
                "onboarding_case_id": str(p.onboarding_case_id) if p.onboarding_case_id else None,
                "start_date": p.start_date.isoformat(),
                "planned_end_date": p.planned_end_date.isoformat(),
                "status": p.status,
                "statusLabel": label_for(PROBATION_STATUS_LABELS, p.status),
                "result": p.result,
                "resultLabel": label_for(PROBATION_RESULT_LABELS, p.result),
                "extension_count": p.extension_count,
            }
            for p in qs.order_by("-planned_end_date")
        ]
        return api_base.ok(request, {"items": items, "total": len(items)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.manage")
def probation_open(request, case_id: str):
    """激活后按 policy 开启试用（同 employment 一份进行中）。"""
    try:
        context = api_base.make_hr05_context(request)
        from hr_onboarding.api.views import _load_case_or_404

        case = _load_case_or_404(context, case_id)
        payload = _payload(request)
        staff_master_id = payload.get("staff_master_id")
        employment_id = payload.get("employment_relationship_id")
        start = _parse_date(payload.get("start_date"))
        planned_end = _parse_date(payload.get("planned_end_date"))
        if not (staff_master_id and employment_id and start and planned_end):
            raise Hr05ApiError("staff_master_id/employment_relationship_id/start_date/planned_end_date 必填")
        probation = ProbationService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).open_probation(
            case,
            staff_master_id=staff_master_id,
            employment_relationship_id=employment_id,
            start_date=start,
            planned_end_date=planned_end,
            policy_version_id=payload.get("policy_version_id", ""),
        )
        return api_base.ok(
            request,
            {"probation_id": str(probation.id), "status": probation.status, "version": probation.version},
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.manage")
def probation_submit_review(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        payload = _payload(request)
        review_type = str(payload.get("review_type", "SELF") or "SELF").upper()
        if review_type not in {"SELF", "COLLEGE", "HR"}:
            raise Hr05ApiError("review_type 必须是 SELF/COLLEGE/HR")
        content = _required_text(payload, "content", "评价内容")
        with transaction.atomic():
            probation = _load_probation_or_404(context, probation_id, for_update=True)
            _check_expected_version(request, payload, probation)
            review = ProbationService(
                tenant_id=context.tenant_id, actor_user_id=context.user_id
            ).submit_review(
                probation,
                review_type=review_type,
                content=content,
                decision=str(payload.get("decision", "") or "").strip(),
            )
            probation.refresh_from_db(fields=["status", "version"])
        return api_base.ok(
            request,
            {"review_id": str(review.id), "status": probation.status, "version": probation.version},
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.finalize")
def probation_confirm(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        payload = _payload(request)
        reason = _required_text(payload, "reason", "转正依据")
        with transaction.atomic():
            probation = _load_probation_or_404(context, probation_id, for_update=True)
            _check_expected_version(request, payload, probation)
            updated = ProbationService(
                tenant_id=context.tenant_id, actor_user_id=context.user_id
            ).confirm(probation, decision_reason=reason, as_of=context.today())
        return api_base.ok(
            request,
            {
                "probation_id": str(updated.id),
                "status": updated.status,
                "result": updated.result,
                "version": updated.version,
            },
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.finalize")
def probation_extend(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        payload = _payload(request)
        new_end = _parse_date(payload.get("new_end_date"))
        if new_end is None:
            raise Hr05ApiError("new_end_date 必填")
        reason = _required_text(payload, "reason", "延期原因")
        with transaction.atomic():
            probation = _load_probation_or_404(context, probation_id, for_update=True)
            _check_expected_version(request, payload, probation)
            updated = ProbationService(
                tenant_id=context.tenant_id, actor_user_id=context.user_id
            ).extend(probation, new_end_date=new_end, reason=reason)
        return api_base.ok(
            request,
            {
                "probation_id": str(updated.id),
                "status": updated.status,
                "planned_end_date": updated.planned_end_date.isoformat(),
                "extension_count": updated.extension_count,
                "version": updated.version,
            },
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.finalize")
def probation_fail(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        payload = _payload(request)
        reason = _required_text(payload, "reason", "不通过原因")
        with transaction.atomic():
            probation = _load_probation_or_404(context, probation_id, for_update=True)
            _check_expected_version(request, payload, probation)
            updated = ProbationService(
                tenant_id=context.tenant_id, actor_user_id=context.user_id
            ).fail(probation, reason=reason)
        return api_base.ok(
            request,
            {
                "probation_id": str(updated.id),
                "status": updated.status,
                "result": updated.result,
                "version": updated.version,
            },
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
