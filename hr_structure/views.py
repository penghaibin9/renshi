"""HR02 页面视图。

原组织树/岗位台账继续保留；新增总览、党政业务关系、编制方案、岗位目录、
历史变更工作区，彻底移除 redirect 占位。
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone

from hr_control_center.context import resolve_tenant_from_request
from hr_structure.models import (
    HrHeadcountQuotaLine,
    HrOrganization,
    HrOrganizationRelation,
    HrOrganizationVersion,
    HrPosition,
    HrPositionReservation,
    HrPostCatalog,
    HrPostCatalogVersion,
    HrStaffingPlan,
    HrStructureChangeCase,
)


SECTION_TITLES = {
    "overview": "组织岗位工作台",
    "relations": "党政组织与业务关系",
    "staffing": "编制方案",
    "catalogs": "岗位目录",
    "history": "组织岗位历史",
}

ORG_TYPE_ZH = {
    "SCHOOL": "学校",
    "CAMPUS": "校区",
    "COLLEGE": "学院",
    "DEPARTMENT": "系部",
    "OFFICE": "职能部门",
    "DIVISION": "处室",
    "SECTION": "科室",
    "TEACHING_RESEARCH_UNIT": "教研室",
    "LAB_CENTER": "实训/实验中心",
    "RESEARCH_INSTITUTE": "研究机构",
    "DIRECT_AFFILIATED_UNIT": "直属单位",
    "PARTY_COMMITTEE": "党委",
    "PARTY_GENERAL_BRANCH": "党总支",
    "PARTY_BRANCH": "党支部",
    "VIRTUAL_ORG": "虚拟组织",
    "TEMP_ORG": "临时组织",
    "OTHER": "其他",
}
RELATION_ZH = {
    "ADMIN_PARENT": "行政隶属",
    "PARTY_PARENT": "党组织隶属",
    "TEACHING_PARENT": "教学隶属",
    "PARTY_COVERS": "党组织覆盖",
    "ADMIN_MATCH": "党政对应",
    "TEACHING_BELONGS_TO": "教学归属",
    "BUSINESS_REPORTS_TO": "业务汇报",
    "BUSINESS_MANAGED_BY": "业务归口管理",
    "SHARED_SERVICE_FOR": "共享服务",
    "TEMP_COORDINATION": "临时协同",
}
PLAN_STATUS_ZH = {
    "DRAFT": "草稿",
    "UNDER_REVIEW": "审核中",
    "RETURNED": "退回修改",
    "REJECTED": "未通过",
    "APPROVED": "已批准待生效",
    "EFFECTIVE": "当前生效",
    "SUPERSEDED": "已被新方案替代",
    "CANCELLED": "已取消",
}
POST_CATEGORY_ZH = {
    "MANAGEMENT": "管理岗位",
    "PROFESSIONAL_TECHNICAL": "专业技术岗位",
    "SKILLED_WORKER": "工勤技能岗位",
    "SPECIAL": "特殊岗位",
}
POSITION_STATUS_ZH = {
    "DRAFT": "草稿",
    "PENDING_APPROVAL": "待审批",
    "ACTIVE": "可用",
    "FROZEN": "已冻结",
    "CLOSED": "已关闭",
    "CANCELLED": "已取消",
}
CHANGE_STATUS_ZH = {
    "DRAFT": "草稿",
    "SUBMITTED": "已提交",
    "UNDER_REVIEW": "审核中",
    "RETURNED": "退回修改",
    "REJECTED": "未通过",
    "APPROVED": "已批准",
    "SCHEDULED": "待到期生效",
    "EFFECTIVE": "已生效",
    "CANCELLED": "已取消",
    "FAILED_EFFECT": "生效失败",
}
CHANGE_TYPE_ZH = {
    "CREATE_ORG": "新增组织",
    "RENAME_ORG": "组织更名",
    "CHANGE_ORG_TYPE": "调整组织类型",
    "REPARENT_ORG": "调整隶属关系",
    "MERGE_ORGS": "组织合并",
    "SPLIT_ORG": "组织拆分",
    "DEACTIVATE_ORG": "停用组织",
    "REACTIVATE_ORG": "恢复组织",
    "CREATE_RELATION": "新增业务关系",
    "CHANGE_RELATION": "调整业务关系",
    "MOVE_POSITION": "岗位转移",
    "CREATE_POSITION": "新增岗位",
    "CHANGE_POSITION": "调整岗位",
    "CLOSE_POSITION": "关闭岗位",
    "ADJUST_STAFFING_QUOTA": "调整人员编制",
    "ADJUST_POSITION_QUOTA": "调整岗位额度",
}


def _tenant_and_permission(request):
    if not request.user.is_superuser and not request.user.has_perm("hr.structure.access"):
        raise PermissionDenied("没有组织岗位管理访问权限")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise PermissionDenied("请选择当前学校后再进入组织岗位管理")
    return int(tenant_id)


def _current_org_name_map(tenant_id, today):
    rows = (
        HrOrganizationVersion.objects.filter(
            tenant_id=tenant_id,
            status="EFFECTIVE",
            validity_from__lte=today,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=today))
        .order_by("organization_id_id", "-version_no")
    )
    result = {}
    for row in rows:
        result.setdefault(row.organization_id_id, row.name)
    return result


@login_required
def workspace(request, section="overview"):
    if section not in SECTION_TITLES:
        section = "overview"
    try:
        tenant_id = _tenant_and_permission(request)
    except PermissionDenied as exc:
        return render(
            request,
            "hr/structure/workspace.html",
            {"section": section, "section_title": SECTION_TITLES[section], "access_error": str(exc)},
            status=403,
        )

    today = timezone.localdate()
    orgs = HrOrganization.objects.filter(tenant_id=tenant_id)
    org_versions = HrOrganizationVersion.objects.filter(tenant_id=tenant_id)
    relations = HrOrganizationRelation.objects.filter(tenant_id=tenant_id)
    plans = HrStaffingPlan.objects.filter(tenant_id=tenant_id)
    catalogs = HrPostCatalog.objects.filter(tenant_id=tenant_id)
    catalog_versions = HrPostCatalogVersion.objects.filter(tenant_id=tenant_id)
    positions = HrPosition.objects.filter(tenant_id=tenant_id)
    reservations = HrPositionReservation.objects.filter(tenant_id=tenant_id)
    changes = HrStructureChangeCase.objects.filter(tenant_id=tenant_id)

    active_org_ids = (
        org_versions.filter(status="EFFECTIVE", validity_from__lte=today)
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=today))
        .values_list("organization_id_id", flat=True)
    )
    current_catalogs = catalog_versions.filter(
        status="ACTIVE", validity_from__lte=today
    ).filter(Q(validity_to__isnull=True) | Q(validity_to__gt=today))

    summary = {
        "active_orgs": orgs.filter(id__in=active_org_ids, identity_status="ACTIVE").count(),
        "active_relations": relations.filter(status="ACTIVE", validity_from__lte=today).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=today)
        ).count(),
        "effective_plans": plans.filter(status="EFFECTIVE", validity_from__lte=today).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=today)
        ).count(),
        "active_catalogs": current_catalogs.values("catalog_id_id").distinct().count(),
        "active_positions": positions.filter(lifecycle_status="ACTIVE", validity_from__lte=today).filter(
            Q(validity_to__isnull=True) | Q(validity_to__gt=today)
        ).count(),
        "held_reservations": reservations.filter(status="HELD", expires_at__gt=timezone.now()).count(),
        "pending_changes": changes.filter(status__in=["SUBMITTED", "UNDER_REVIEW", "RETURNED", "APPROVED", "SCHEDULED"]).count(),
        "failed_changes": changes.filter(status="FAILED_EFFECT").count(),
    }

    focus_items = []
    if summary["failed_changes"]:
        focus_items.append({
            "level": "danger",
            "title": f"{summary['failed_changes']} 个组织岗位变更生效失败",
            "desc": "先处理执行失败，再继续下游人员、合同或薪酬协同，避免组织真值分叉。",
            "url": "/hr/structure/history",
            "action": "查看变更历史",
        })
    if summary["pending_changes"]:
        focus_items.append({
            "level": "warning",
            "title": f"{summary['pending_changes']} 个组织岗位变更仍在办理",
            "desc": "重点检查待审核、退回、已批准待生效和未来生效的重组事项。",
            "url": "/hr/structure/history",
            "action": "进入变更工作区",
        })
    if summary["held_reservations"]:
        focus_items.append({
            "level": "info",
            "title": f"{summary['held_reservations']} 个岗位额度正在预占",
            "desc": "岗位预占只是暂时锁额度，不等于人员已经正式任职。",
            "url": "/hr/structure/positions",
            "action": "查看岗位台账",
        })

    name_map = _current_org_name_map(tenant_id, today)

    relation_rows = []
    for row in relations.order_by("relation_type", "source_org_id_id")[:80]:
        relation_rows.append({
            "source": name_map.get(row.source_org_id_id, row.source_org_id.stable_code),
            "target": name_map.get(row.target_org_id_id, row.target_org_id.stable_code),
            "type": RELATION_ZH.get(row.relation_type, row.relation_type),
            "status": "当前有效" if row.status == "ACTIVE" else "已关闭",
            "validity_from": row.validity_from,
            "validity_to": row.validity_to,
        })

    staffing_rows = []
    for row in plans.annotate(total_headcount=Sum("headcount_lines__authorized_headcount")).order_by("-plan_year", "-version_no")[:40]:
        staffing_rows.append({
            "code": row.code,
            "name": row.name,
            "year": row.plan_year,
            "version": row.version_no,
            "status": PLAN_STATUS_ZH.get(row.status, row.status),
            "status_code": row.status,
            "validity_from": row.validity_from,
            "validity_to": row.validity_to,
            "headcount": row.total_headcount or 0,
            "basis": row.basis_document_no or "—",
        })

    catalog_rows = []
    for row in current_catalogs.select_related("catalog_id", "grade_scheme_id").order_by("category", "name")[:80]:
        catalog_rows.append({
            "code": row.catalog_id.stable_code,
            "name": row.name,
            "category": POST_CATEGORY_ZH.get(row.category, row.category),
            "subcategory": row.subcategory or "—",
            "version": row.version_no,
            "control_mode": "岗位实例控制" if row.control_mode == "POSITION_CONTROL" else "岗位池额度控制",
            "fte": row.standard_fte,
            "credential_required": row.requires_professional_credential,
        })

    history_rows = []
    for row in org_versions.select_related("organization_id").order_by("-created_at")[:50]:
        history_rows.append({
            "code": row.organization_id.stable_code,
            "name": row.name,
            "type": ORG_TYPE_ZH.get(row.org_type, row.org_type),
            "version": row.version_no,
            "status": row.get_status_display(),
            "validity_from": row.validity_from,
            "validity_to": row.validity_to,
            "source": row.source,
        })
    change_rows = [
        {
            "case_no": row.case_no,
            "title": row.title,
            "type": CHANGE_TYPE_ZH.get(row.change_type, row.change_type),
            "status": CHANGE_STATUS_ZH.get(row.status, row.status),
            "status_code": row.status,
            "effective_date": row.requested_effective_date,
            "reason": row.reason or "—",
        }
        for row in changes.order_by("-created_at")[:50]
    ]

    return render(
        request,
        "hr/structure/workspace.html",
        {
            "section": section,
            "section_title": SECTION_TITLES[section],
            "today": today,
            "summary": summary,
            "focus_items": focus_items,
            "relation_rows": relation_rows,
            "staffing_rows": staffing_rows,
            "catalog_rows": catalog_rows,
            "history_rows": history_rows,
            "change_rows": change_rows,
        },
    )


@login_required
def hr_organizations(request):
    """HR02-01 组织机构页面。"""
    return render(request, "hr/structure/organizations.html")


@login_required
def hr_positions(request):
    """HR02-05 岗位编制台账页面。"""
    return render(request, "hr/structure/positions.html")
