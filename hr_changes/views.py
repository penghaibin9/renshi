"""HR06 server-rendered workspaces with the same permission boundaries as canonical APIs."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr_changes.context import HrChangeContextError, resolve_tenant_from_request
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.case_list import CaseListSelector


def _page_context(request):
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        return None, render(
            request,
            "hr_changes/error.html",
            {
                "error_code": "TENANT_CONTEXT_REQUIRED",
                "error_message": "请选择当前学校（多学校账号需明确学校上下文）",
            },
            status=403,
        )
    return tenant_id, None


@login_required
@require_hr_change_permission("hr.change.view")
def change_center(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.context import build_hr_change_context

    try:
        ctx = build_hr_change_context(tenant_id=tenant_id, user_id=request.user.id)
    except HrChangeContextError:
        return render(
            request,
            "hr_changes/error.html",
            {"error_code": "SCOPE_DENIED", "error_message": "数据范围不合法"},
            status=403,
        )
    selector = CaseListSelector(ctx)
    view = request.GET.get("view", "initiated")
    if view not in {"initiated", "todos", "approval", "waiting", "effective", "anomalies"}:
        view = "initiated"
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    filters = {
        "keyword": request.GET.get("q", "").strip(),
        "action_code": request.GET.get("action", "").strip(),
        "organization_code": request.GET.get("org", "").strip(),
        "period": request.GET.get("period", "").strip(),
    }
    data = selector.list(
        view=view,
        user_id=request.user.id,
        page=page,
        page_size=10,
        **filters,
    )
    stats = selector.stats(request.user.id)
    counts = selector.view_counts(request.user.id)
    view_tabs = [
        {"key": "initiated", "label": "我发起的", "count": counts["initiated"]},
        {"key": "todos", "label": "待我处理", "count": counts["todos"]},
        {"key": "approval", "label": "审批中", "count": counts["approval"]},
        {"key": "waiting", "label": "待生效", "count": counts["waiting"]},
        {"key": "effective", "label": "已生效", "count": counts["effective"]},
        {"key": "anomalies", "label": "异常", "count": counts["anomalies"]},
    ]
    upcoming = selector.list(
        view="waiting",
        user_id=request.user.id,
        page=1,
        page_size=4,
    )["items"]
    return render(
        request,
        "hr_changes/change_center.html",
        {
            "view": view,
            "view_tabs": view_tabs,
            "items": data["items"],
            "total": data["total"],
            "page": data["page"],
            "page_size": data["pageSize"],
            "has_next": data["hasNext"],
            "stats": stats,
            "filter_options": selector.filter_options(),
            "filters": filters,
            "has_filters": any(filters.values()),
            "upcoming": upcoming,
            "request": request,
        },
    )


@login_required
@require_hr_change_permission("hr.change.transfer.create")
def change_new(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    return render(request, "hr_changes/change_new.html", {})


@login_required
@require_hr_change_permission("hr.change.view")
def future_changes(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.models import HrPersonnelChangeCase

    cases = (
        HrPersonnelChangeCase.objects.filter(
            tenant_id=tenant_id, status="APPROVED_WAITING_EFFECTIVE"
        )
        .select_related("action_id", "staff_master_id", "target_org_id")
        .order_by("requested_effective_at")
    )
    return render(request, "hr_changes/future_changes.html", {"cases": cases})


@login_required
@require_hr_change_permission("hr.change.view")
def change_detail(request, case_id):
    tenant_id, err = _page_context(request)
    if err:
        return err
    data = CaseDetailSelector(tenant_id).get(case_id)
    if data is None:
        return render(
            request,
            "hr_changes/error.html",
            {"error_code": "CHANGE_NOT_FOUND", "error_message": "异动案件不存在"},
            status=404,
        )
    return render(request, "hr_changes/change_detail.html", {"case": data})


@login_required
@require_hr_change_permission("hr.change.transfer.create")
def transfers(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.context import build_hr_change_context
    from hr_changes.selectors.transfer_selector import TransferSelector

    try:
        build_hr_change_context(tenant_id=tenant_id, user_id=request.user.id)
    except HrChangeContextError:
        return render(
            request,
            "hr_changes/error.html",
            {"error_code": "SCOPE_DENIED", "error_message": "数据范围不合法"},
            status=403,
        )
    data = TransferSelector(tenant_id).list()
    return render(
        request,
        "hr_changes/transfers.html",
        {"items": data["items"], "total": data["total"]},
    )


@login_required
@require_hr_change_permission("hr.change.identity_change.create")
def job_identity(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.selectors.identity_selector import IdentitySelector

    data = IdentitySelector(tenant_id).list()
    return render(
        request,
        "hr_changes/job_identity.html",
        {"items": data["items"], "total": data["total"]},
    )


@login_required
@require_hr_change_permission("hr.change.temporary.create")
def secondments(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.selectors.temporary_selector import TemporarySelector

    data = TemporarySelector(tenant_id).list()
    return render(
        request,
        "hr_changes/secondments.html",
        {"items": data["items"], "stats": data["stats"]},
    )


@login_required
@require_hr_change_permission("hr.change.ledger.view")
def ledger(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.selectors.ledger import LedgerSelector

    data = LedgerSelector(tenant_id).list(
        status=request.GET.get("status") or None,
        action_code=request.GET.get("action") or None,
    )
    return render(
        request,
        "hr_changes/ledger.html",
        {"items": data["items"], "total": data["total"]},
    )


@login_required
@require_hr_change_permission("hr.change.submit")
def change_preview(request, case_id):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.models import HrPersonnelChangeCase
    from hr_changes.services.impact_service import ImpactService

    case = HrPersonnelChangeCase.objects.filter(tenant_id=tenant_id, id=case_id).first()
    if case is None:
        return render(
            request,
            "hr_changes/error.html",
            {"error_code": "CHANGE_NOT_FOUND", "error_message": "异动案件不存在"},
            status=404,
        )
    result = ImpactService(tenant_id).compute(case)
    return render(
        request,
        "hr_changes/change_preview.html",
        {
            "case": case,
            "blockers": result["blockers"],
            "warnings": result["warnings"],
        },
    )
