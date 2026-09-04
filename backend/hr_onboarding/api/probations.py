"""
hr_onboarding/api/probations.py

HR05-05 试用与转正 API（总册 §17.7）。
"""

from __future__ import annotations

from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.api.labels import (
    label_for,
    PROBATION_RESULT_LABELS,
    PROBATION_STATUS_LABELS,
)
from hr_onboarding.constants import ProbationStatus
from hr_onboarding.models import HrProbationCase
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.services.probation_service import ProbationService


def _load_probation_or_404(context, probation_id: str):
    try:
        probation = HrProbationCase.objects.filter(
            tenant_id=context.tenant_id, id=probation_id
        ).first()
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
        staff_master_id = request.POST.get("staff_master_id")
        employment_id = request.POST.get("employment_relationship_id")
        start = _parse_date(request.POST.get("start_date"))
        planned_end = _parse_date(request.POST.get("planned_end_date"))
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
            policy_version_id=request.POST.get("policy_version_id", ""),
        )
        return api_base.ok(request, {"probation_id": str(probation.id), "status": probation.status})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.manage")
def probation_submit_review(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        probation = _load_probation_or_404(context, probation_id)
        review_type = request.POST.get("review_type", "SELF")
        review = ProbationService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).submit_review(
            probation,
            review_type=review_type,
            content=request.POST.get("content", ""),
            decision=request.POST.get("decision", ""),
        )
        return api_base.ok(request, {"review_id": str(review.id)})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.finalize")
def probation_confirm(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        probation = _load_probation_or_404(context, probation_id)
        updated = ProbationService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).confirm(probation, decision_reason=request.POST.get("reason", ""), as_of=context.today())
        return api_base.ok(
            request, {"probation_id": str(updated.id), "status": updated.status, "result": updated.result}
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.finalize")
def probation_extend(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        probation = _load_probation_or_404(context, probation_id)
        new_end = _parse_date(request.POST.get("new_end_date"))
        if new_end is None:
            raise Hr05ApiError("new_end_date 必填")
        updated = ProbationService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).extend(probation, new_end_date=new_end, reason=request.POST.get("reason", ""))
        return api_base.ok(
            request,
            {
                "probation_id": str(updated.id),
                "status": updated.status,
                "planned_end_date": updated.planned_end_date.isoformat(),
                "extension_count": updated.extension_count,
            },
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.probation.finalize")
def probation_fail(request, probation_id: str):
    try:
        context = api_base.make_hr05_context(request)
        probation = _load_probation_or_404(context, probation_id)
        updated = ProbationService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).fail(probation, reason=request.POST.get("reason", ""))
        return api_base.ok(
            request, {"probation_id": str(updated.id), "status": updated.status, "result": updated.result}
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
