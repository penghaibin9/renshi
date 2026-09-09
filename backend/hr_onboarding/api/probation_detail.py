"""Read one authorized HR05 probation and a bounded page of its own facts.

No decision, transition, provider fallback or secondary personnel record is
created here. The existing manage permission is school-level; narrower scopes
are rejected until a trusted object-scope resolver is available for HR05.
"""

from datetime import date, datetime
from uuid import UUID

from django.db.models import Q
from django.views.decorators.http import require_GET

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError, PermissionDeniedError
from hr_onboarding.api.labels import (
    PROBATION_RESULT_LABELS,
    PROBATION_STATUS_LABELS,
    label_for,
)
from hr_onboarding.constants import ProbationStatus
from hr_onboarding.models import (
    HrProbationCase,
    HrProbationExtension,
    HrProbationGoal,
    HrProbationReview,
)
from hr_onboarding.permissions import require_hr05_permission
from hr_onboarding.policies.state_machine import validate_probation_transition

PAGE_SIZE = 20
SECTIONS = {
    "goals": (
        HrProbationGoal,
        ("title", "id"),
        ("id", "category", "title", "description", "evaluator_role", "evidence_required"),
    ),
    "reviews": (
        HrProbationReview,
        ("-created_at", "-id"),
        ("id", "review_type", "reviewer_id", "content", "decision", "submitted_at", "version", "created_at"),
    ),
    "extensions": (
        HrProbationExtension,
        ("-created_at", "-id"),
        ("id", "old_end_date", "new_end_date", "reason", "approval", "created_by", "created_at"),
    ),
}
TERMINAL_STATUSES = {
    ProbationStatus.CONFIRMED,
    ProbationStatus.FAILED,
    ProbationStatus.CANCELLED,
}


def _json_value(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _read_page(value):
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > 5:
        raise Hr05ApiError("页码必须是 1 到 10000 的整数")
    page = int(text)
    if not 1 <= page <= 10000:
        raise Hr05ApiError("页码必须是 1 到 10000 的整数")
    return page


def _section_page(probation, tenant_id, section, page):
    result = {"key": section, "page": page, "pageSize": PAGE_SIZE, "items": [], "hasMore": False}
    if section == "summary":
        return result
    model, order, fields = SECTIONS[section]
    start = (page - 1) * PAGE_SIZE
    rows = list(
        model.objects.filter(tenant_id=tenant_id, probation_case_id=probation.id)
        .order_by(*order)
        .values(*fields)[start : start + PAGE_SIZE + 1]
    )
    result["hasMore"] = len(rows) > PAGE_SIZE
    result["items"] = [
        {key: _json_value(value) for key, value in row.items()}
        for row in rows[:PAGE_SIZE]
    ]
    return result


def _decision_capabilities(request, probation):
    can_finalize = bool(
        request.user.is_superuser or request.user.has_perm("hr05.probation.finalize")
    )
    if not can_finalize:
        return {"confirm": False, "extend": False, "fail": False}
    return {
        "confirm": validate_probation_transition(
            probation.status, ProbationStatus.CONFIRMED
        ).allowed,
        # ProbationService intentionally supports repeated extensions and keeps
        # every old/new date pair as history; mirror that established contract.
        "extend": probation.status not in TERMINAL_STATUSES,
        "fail": validate_probation_transition(
            probation.status, ProbationStatus.FAILED
        ).allowed,
    }


@require_GET
@require_hr05_permission("hr05.probation.manage")
def probation_detail(request, probation_id):
    """Canonical GET via the existing canonical_hr_api route adapter."""
    try:
        context = api_base.make_hr05_context(request)
        if context.scope.scope_type != "SCHOOL" or context.scope.org_id is not None:
            raise PermissionDeniedError("此入口仅支持学校级试用管理范围")
        section = request.GET.get("section", "summary")
        if section != "summary" and section not in SECTIONS:
            raise Hr05ApiError("不支持的试用记录分区")
        page = _read_page(request.GET.get("page", "1"))
        if section == "summary" and page != 1:
            raise Hr05ApiError("试用摘要没有分页")
        try:
            object_id = UUID(str(probation_id))
        except (ValueError, TypeError, AttributeError):
            raise NotFoundError("试用记录不存在或无权访问") from None
        probation = HrProbationCase.objects.filter(
            Q(onboarding_case__isnull=True) | Q(onboarding_case__tenant_id=context.tenant_id),
            tenant_id=context.tenant_id,
            id=object_id,
        ).first()
        if probation is None:
            raise NotFoundError("试用记录不存在或无权访问")
        fields = (
            "id", "staff_master_id", "employment_relationship_id", "onboarding_case_id",
            "start_date", "planned_end_date", "actual_end_date", "status", "result",
            "extension_count", "policy_version_id", "version", "created_at", "updated_at",
        )
        record = {name: _json_value(getattr(probation, name)) for name in fields}
        record["statusLabel"] = label_for(PROBATION_STATUS_LABELS, probation.status)
        record["resultLabel"] = label_for(PROBATION_RESULT_LABELS, probation.result)
        return api_base.ok(request, {
            "probation": record,
            "section": _section_page(probation, context.tenant_id, section, page),
            "canViewCase": bool(request.user.is_superuser or request.user.has_perm("hr05.case.view")),
            "decisionCapabilities": _decision_capabilities(request, probation),
        })
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
