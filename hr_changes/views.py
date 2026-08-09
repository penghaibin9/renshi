"""
hr_changes/views.py —— HR06 页面视图（S3 起逐模块实现）。

- /hr/changes/            异动申请中心（统计卡 + 视图列表）
- /hr/changes/new         发起向导
- /hr/changes/future      未来生效队列
- /hr/changes/:id         案件详情
- /hr/changes/:id/preview 影响预览
- /hr/changes/transfers   校内调动（S4）
- /hr/changes/job-identity 岗位与身份变更（S5）
- /hr/changes/secondments 借调挂职（S6）
- /hr/changes/ledger      异动台账（S7）
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr_changes.context import HrChangeContextError, resolve_tenant_from_request
from hr_changes.selectors.case_detail import CaseDetailSelector
from hr_changes.selectors.case_list import CaseListSelector


def _page_context(request):
    """服务端解析 tenant；无学校上下文时给出错误页（fail-closed）。"""
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        return None, render(
            request,
            "hr_changes/error.html",
            {"error_code": "TENANT_CONTEXT_REQUIRED", "error_message": "请选择当前学校（多学校账号需明确学校上下文）"},
            status=403,
        )
    return tenant_id, None


@login_required
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
    data = selector.list(view=view, user_id=request.user.id)
    view_tabs = [
        ("initiated", "我的发起"),
        ("todos", "我的待办"),
        ("approval", "审批中"),
        ("waiting", "待生效"),
        ("effective", "已生效"),
        ("anomalies", "异常"),
    ]
    return render(
        request,
        "hr_changes/change_center.html",
        {
            "view": view,
            "view_tabs": view_tabs,
            "items": data["items"],
            "total": data["total"],
            "stats": selector.stats(request.user.id),
            "request": request,
        },
    )


@login_required
def change_new(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    return render(request, "hr_changes/change_new.html", {})


@login_required
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
    return render(request, "hr_changes/transfers.html", {"items": data["items"], "total": data["total"]})


@login_required
def job_identity(request):
    tenant_id, err = _page_context(request)
    if err:
        return err
    from hr_changes.api.identity_changes import IDENTITY_ACTIONS
    from hr_changes.models import HrPersonnelChangeCase

    cases = (
        HrPersonnelChangeCase.objects.filter(
            tenant_id=tenant_id, action_id__code__in=IDENTITY_ACTIONS
        )
        .select_related("action_id", "staff_master_id", "target_org_id")
        .order_by("-created_at")
    )
    return render(request, "hr_changes/job_identity.html", {"cases": cases})


@login_required
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
        {"case": case, "blockers": result["blockers"], "warnings": result["warnings"]},
    )
