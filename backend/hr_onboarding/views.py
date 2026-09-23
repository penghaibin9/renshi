"""
hr_onboarding/views.py

HR05 页面视图（Django Template 渲染，数据走 JSON API，模板薄）。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from hr_onboarding.permissions import require_hr05_permission, require_hr05_any_permission


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_prehires(request):
    """HR05-01 待报到人员列表（数据由 /api/hr/v1/onboarding/cases 提供）。"""
    from hr_onboarding.services.workflow_service import permitted
    return render(request, "hr/onboarding/prehires/list.html", {"can_configure_onboarding":
        permitted(request.user, "hr05.template.manage") or permitted(request.user, "hr05.template.publish")})


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_case_detail(request, case_id):
    """HR05-01 case 详情页（Tabs：报到准备/个人资料/材料/岗位/Portal/历史）。"""
    return render(request, "hr/onboarding/prehires/detail.html", {"case": {"id": case_id}})


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_reporting(request):
    """HR05-02 报到登记列表；禁止用空 case 渲染单 case 写操作页。"""
    return render(request, "hr/onboarding/reporting/list.html")


@login_required
@require_hr05_permission("hr05.report.checkin")
def hr05_report_checkin(request, case_id):
    """HR05-02 单 case 报到登记页（三栏：报到事实/组织岗位/生效前闸门）。"""
    return render(request, "hr/onboarding/reporting/checkin.html", {"case": {"id": case_id}})


@login_required
@require_hr05_permission("hr05.material.review")
def hr05_material_workspace(request):
    """HR05-03 材料核验工作台；由浏览器显式选择 case 后读取 canonical API。"""
    return render(request, "hr/onboarding/materials/workspace.html")


@login_required
@require_hr05_any_permission("hr05.task.manage", "hr05.task.complete", "hr05.task.waive")
def hr05_collaboration_center(request):
    """HR05-04 协同任务中心；由浏览器显式选择 case 后读取 canonical API。"""
    return render(request, "hr/onboarding/collaboration/center.html")


@login_required
@require_hr05_permission("hr05.probation.manage")
def hr05_probation_list(request):
    """HR05-05 试用转正列表（真实列表 API，不复用单条详情模板）。"""
    return render(request, "hr/onboarding/probations/list.html")


@login_required
@require_hr05_permission("hr05.probation.manage")
def hr05_probation_detail(request, probation_id):
    """HR05-05 试用详情（目标/自评/学院评价/审核/延长记录 + 决策栏）。"""
    return render(request, "hr/onboarding/probations/detail.html", {"probation": {"id": probation_id}})


@login_required
@require_hr05_any_permission("hr05.template.manage", "hr05.template.publish")
@ensure_csrf_cookie
def hr05_school_templates(request):
    from hr_onboarding.api.base import make_hr05_context
    from hr_onboarding.services.workflow_service import permitted
    from django.core.exceptions import PermissionDenied
    from hr_onboarding.api.base import handle_hr05_error
    from hr_onboarding.api.exceptions import Hr05ApiError
    try:
        ctx = make_hr05_context(request)
    except Hr05ApiError as exc:
        return handle_hr05_error(request, exc)
    if ctx.scope.scope_type != "SCHOOL":
        raise PermissionDenied("校本方案须学校级授权")
    from hr_onboarding.constants import ResponsibleRole, BlockingLevel, MaterialBlockingPhase, StaffCategoryCode, EmploymentType
    from hr_onboarding.api.labels import RESPONSIBLE_ROLE_LABELS, BLOCKING_LEVEL_LABELS
    return render(request, "hr/onboarding/configuration/workbench.html", {
        "can_configure_onboarding": True,
        "can_manage_templates": permitted(request.user, "hr05.template.manage"),
        "can_publish_templates": permitted(request.user, "hr05.template.publish"),
        "template_options": {
            "roles": [{"value": x, "label": RESPONSIBLE_ROLE_LABELS.get(x,x)} for x in ResponsibleRole.values],
            "blocks": [{"value": x, "label": BLOCKING_LEVEL_LABELS.get(x,x)} for x in BlockingLevel.values],
            "phases": [{"value": x, "label": {"PRE_REPORT":"报到前", "REPORT":"报到时", "ACTIVATION":"正式生效前", "POST_ACTIVATION":"正式生效后", "PROBATION":"试用期"}[x]} for x in MaterialBlockingPhase.values],
            "staff": list(StaffCategoryCode.values), "employment": list(EmploymentType.values),
        }
    })
