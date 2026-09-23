"""Read-only first-use navigator; all progress comes from scoped server facts."""
from __future__ import annotations

from django.conf import settings
from django.urls import reverse
from base.first_use_policy import first_use_progress, OPTIONAL_PROFILE_FIELDS
from base.models import Company, CompanyGroupAssignment, Department, JobPosition
from employee.models import Employee
from horilla.horilla_middlewares import get_selected_company
from horilla_auth.models import HorillaUser


def resolve_admin_school(request):
    """Do not infer the first school from an all/invalid tenant context.

    The single-school fallback is allowed only for its local superuser or an
    account linked to that school. It never depends on client-provided IDs.
    """
    if getattr(settings, "HR_INSTALLATION_MODE", "standalone_school") != "standalone_school":
        return None
    schools = list(Company.objects.order_by("pk")[:2])
    if len(schools) != 1:
        return None
    school = schools[0]
    selected = get_selected_company()
    if selected not in (None, "", "all"):
        try:
            if int(selected) != school.pk:
                return None
        except (TypeError, ValueError):
            return None
    if request.user.is_superuser:
        return school
    # Explicitly scoped lookup; the controlled unscoped manager is necessary
    # only because an account may not yet have a selected-company session.
    linked = Employee.objects.entire().filter(
        employee_user_id_id=request.user.pk,
        employee_work_info__company_id_id=school.pk,
        is_active=True,
    ).exists()
    return school if linked and request.user.is_active else None


def _has_complete_hr03_staff_authority(tenant_id: int) -> bool:
    """True only when a current staff member has one coherent authority chain.

    Readiness is a *current fact*, not merely four rows that once existed.  The
    same active Employment must own an active Assignment whose effective window
    contains today.  After HR02 cutover, that Assignment must also reference the
    tenant's HR02 organization authority; a legacy-only department assignment can
    no longer turn first-use green.
    """
    from django.db.models import Exists, OuterRef, Q
    from django.utils import timezone

    from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment, HrStaffMaster
    from hr_structure.services.cutover import Hr02CutoverService

    today = timezone.localdate()
    assignment_qs = (
        HrStaffAssignment.objects.filter(
            tenant_id=tenant_id,
            employment_relationship_id=OuterRef("pk"),
            status="ACTIVE",
            effective_from__lte=today,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=today))
    )
    if Hr02CutoverService().get_mode(tenant_id) == "HR02_AUTHORITY":
        assignment_qs = assignment_qs.filter(organization_id__tenant_id=tenant_id)

    relationship_qs = (
        HrEmploymentRelationship.objects.filter(
            tenant_id=tenant_id,
            staff_id=OuterRef("pk"),
            status="ACTIVE",
            effective_from__lte=today,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=today))
        .annotate(has_current_assignment=Exists(assignment_qs))
        .filter(has_current_assignment=True)
    )

    return (
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            person_id__tenant_id=tenant_id,
        )
        .annotate(has_current_relationship=Exists(relationship_qs))
        .filter(has_current_relationship=True)
        .exists()
    )


def build_first_use(request, school):
    user = request.user
    if school is None:
        result = first_use_progress({"scope_ok": False})
        result.update({"profile_pending": [], "profile_url": "", "next_url": "", "next_help": "请联系部署管理员核对学校绑定；不会自动选择其他学校。"})
        return result
    can = lambda perm: user.is_superuser or user.has_perm(perm)
    department_ready = Department.objects.entire().filter(company_id=school, is_active=True).exists()
    position_ready = JobPosition.objects.entire().filter(company_id=school, is_active=True).exists()
    # A bootstrap Employee is only an account compatibility record. It must
    # NEVER count as the first canonical HR03 teacher.
    staff_ready = None
    if can("hr.staff.view") or can("hr.staff.import"):
        staff_ready = _has_complete_hr03_staff_authority(school.pk)
    roles_ready = None
    if user.is_superuser:
        if getattr(settings, "COMPANY_SCOPED_PERMISSIONS", False):
            roles_ready = CompanyGroupAssignment.objects.filter(
                company=school, user__is_active=True, user__is_superuser=False,
                group__permissions__isnull=False,
            ).exists()
        else:
            ids = Employee.objects.entire().filter(employee_work_info__company_id=school).values_list("employee_user_id_id", flat=True)
            roles_ready = HorillaUser.objects.filter(id__in=ids, is_active=True, is_superuser=False, groups__permissions__isnull=False).exists()
    result = first_use_progress({"scope_ok": True, "school_count": 1,
        "organization_ready": department_ready and position_ready,
        "staff_ready": staff_ready, "roles_ready": roles_ready})
    actions = {
        "school": ("company-view", "base.change_company", "维护本校名称；地址和校标可以后补。"),
        "organization": ("department-view" if not department_ready else "job-position-view",
                         "base.add_department" if not department_ready else "base.add_jobposition", "先录入真实学院、部门和岗位，不自动编造组织数据。"),
        "staff": (None, "hr.staff.import", "下载 Excel 模板 → 填写教职工 → 校验预览 → 确认写入。系统只有回读到自然人、教职工身份、聘用关系、任职四层正式记录后才算完成；导入人员不等于已经开通账号。"),
        "roles": ("user-group-view", None, "由本校超级管理员配置日常管理角色，检查权限后交给业务人员使用。"),
        "acceptance": (None, None, "基础数据准备完成不代表合同、考核、工资或备份恢复已经验收。"),
    }
    for step in result["steps"]:
        route, perm, help_text = actions[step["code"]]
        allowed = user.is_superuser if perm is None else can(perm)
        url = reverse(route) if route and allowed else "/hr/staff/" if step["code"] == "staff" and allowed else ""
        step.update({"url": url, "help": help_text, "state_label": {"done": "已读取到记录", "pending": "待办理", "unknown": "需有权限的管理员核对"}[step["state"]]})
    next_step = next((s for s in result["steps"] if s["code"] == result["next_code"]), None)
    result["next_url"] = next_step["url"] if next_step else "#sysadmin-health"
    result["next_help"] = next_step["help"] if next_step else actions["acceptance"][2]
    result["profile_pending"] = [label for key, (_, label) in OPTIONAL_PROFILE_FIELDS.items()
        if key.startswith("company_") and not getattr(school, key.removeprefix("company_"), "")]
    result["profile_url"] = reverse("company-view") if can("base.change_company") else ""
    return result
