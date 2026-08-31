"""
hr_external/views.py —— HR08 页面视图（S1 骨架 + S3 外聘教师库）。

页面：
- /hr/external-teachers/                    外聘教师库（HR08-01）
- /hr/external-teachers/pool/               候选池
- /hr/external-teachers/<profile_id>/       Profile 详情
"""

from datetime import date, timedelta

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from hr_external.context import resolve_tenant_from_request
from hr_external.display_labels import (
    contribution_verification_label,
    engagement_status_label,
    ethics_status_label,
    exit_reason_label,
    exit_status_label,
    identity_verification_label,
    pool_status_label,
    renewal_status_label,
    task_status_label,
)
from hr_external.models import (
    HrExternalContribution,
    HrExternalEngagement,
    HrExternalHiringCase,
    HrExternalIndustryProfile,
    HrExternalTeacherProfile,
    HrExternalWorkspace,
)
from hr_external.selectors import list_external_profiles
from hr_external.selectors.profile_selector import ProfileFilterSpec
from hr_external.services.category_service import CategoryService
from hr_external.services.compliance_service import ComplianceService


_ACTIVE_ENGAGEMENT_STATUSES = (
    "ACTIVE",
    "REVIEW_DUE",
    "RENEWAL_IN_PROGRESS",
    "SIGNED_WAITING_EFFECTIVE",
)
_HIRING_STATUS_LABELS = {
    "DRAFT": "草稿",
    "RETURNED": "已退回",
    "SUBMITTED": "已提交",
    "UNDER_COLLEGE_REVIEW": "学院审批",
    "UNDER_HR_REVIEW": "人事审批",
    "UNDER_SCHOOL_APPROVAL": "学校审批",
    "APPROVED": "已批准",
    "WAITING_AGREEMENT": "待签协议",
    "READY_TO_ACTIVATE": "待激活",
    "ACTIVATED": "已生效",
    "REJECTED": "已拒绝",
    "WITHDRAWN": "已撤回",
    "CANCELLED": "已取消",
}
_RENEWAL_DECISION_LABELS = {
    "RENEW": "续聘",
    "RENEW_WITH_CHANGES": "调整后续聘",
    "CHANGE_CATEGORY": "变更类别",
    "CHANGE_HOST_ORG": "变更主办学院",
    "CONVERT_TO_REGULAR_HR_PROCESS": "转正式员工流程",
    "DO_NOT_RENEW": "不予续聘",
    "NEEDS_REVIEW": "需复核",
}
_TASK_TYPE_LABELS = {
    "TEACHING": "教学",
    "PRACTICE_GUIDANCE": "实训指导",
    "INDUSTRY_MENTOR": "产业导师",
    "PROGRAM_DEVELOPMENT": "专业建设",
    "RESEARCH_COLLABORATION": "科研合作",
    "SKILL_TRAINING": "技能培训",
    "FACULTY_DEVELOPMENT": "教师发展",
    "STUDENT_MENTORING": "学生指导",
    "OTHER": "其他",
}
_SOURCE_LABELS = {"ACADEMIC": "教务", "HR08": "人事系统", "LEGACY_IMPORT": "历史导入", "OTHER": "其他"}
_WORKSPACE_TYPE_LABELS = {
    "SKILL_MASTER_WORKSHOP": "技能大师工作室",
    "INDUSTRY_TEACHING_WORKSHOP": "产业教学工作室",
    "PRACTICE_BASE": "实践基地",
    "INDUSTRY_ACADEMIC_PLATFORM": "产学合作平台",
    "OTHER": "其他",
}
_WORKSPACE_STATUS_LABELS = {"DRAFT": "草稿", "ACTIVE": "运行中", "SUSPENDED": "已暂停", "ENDED": "已结束", "ARCHIVED": "已归档"}
_CONTRIBUTION_TYPE_LABELS = {
    "COURSE_CO_BUILD": "课程共建",
    "TRAINING_PROJECT": "实训项目",
    "PROGRAM_DEVELOPMENT": "专业建设",
    "TALENT_TRAINING_CONSULT": "人才培养咨询",
    "INDUSTRY_ACADEMIC_COOP": "产学合作",
    "TECH_ATTACK": "技术攻关",
    "STUDENT_PROJECT_GUIDANCE": "学生项目指导",
    "TEACHER_PRACTICE_GUIDANCE": "教师实践指导",
    "SKILL_COMPETITION_GUIDANCE": "技能竞赛指导",
    "APPRENTICESHIP_GUIDANCE": "学徒制指导",
    "FACULTY_TRAINING": "师资培训",
    "INDUSTRY_RESOURCE_IMPORT": "产业资源引入",
    "OTHER": "其他",
}
_CONTRIBUTION_STATUS_LABELS = {"DRAFT": "草稿", "SUBMITTED": "已提交", "UNDER_REVIEW": "核验中", "VERIFIED": "已核验", "REJECTED": "已拒绝", "RETURNED": "已退回"}
_COMMON = {
    "home": ("外聘教师库", "统一管理外部人才档案、聘期与在校服务事实。"),
    "pool": ("候选人才池", "从已核验档案中筛选可合作人才，不在页面伪造推荐结论。"),
    "industry": ("产业教授与技能大师", "跟踪产业背景、专项成果和校企协同空间。"),
    "hiring": ("聘用审批", "从候选档案发起申请，经合规检查、分级审批和正式协议后生效。"),
    "tasks": ("教学与服务任务", "任务接受、履行、验收和工作量依据全程留痕。"),
    "renewals": ("续聘中心", "聘期到期先评估再决策，续聘生成新聘期而非覆盖旧记录。"),
    "exits": ("退出中心", "结束当前聘期并回收权限，完整保留历史任务、成果和协议。"),
}


def _require_tenant(request):
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED")
    return tenant_id


def _ensure_categories(tenant_id):
    CategoryService().ensure_default_categories(tenant_id)


def _allowed(user, permission):
    return user.is_superuser or user.has_perm(permission)


def _workspace_context(request, section):
    title, description = _COMMON[section]
    return {
        "section": section,
        "section_title": title,
        "section_description": description,
        "can_profile_create": _allowed(request.user, "hr08.profile.create"),
        "can_hiring_create": _allowed(request.user, "hr08.hiring.create"),
        "can_hiring_approve": _allowed(request.user, "hr08.hiring.approve"),
        "can_hiring_activate": _allowed(request.user, "hr08.hiring.activate"),
        "can_task_manage": _allowed(request.user, "hr08.task.manage"),
        "can_task_verify": _allowed(request.user, "hr08.task.verify"),
        "can_renewal_decide": _allowed(request.user, "hr08.renewal.decide"),
        "can_exit_manage": _allowed(request.user, "hr08.exit.manage"),
    }


def _organization_labels(tenant_id, organization_ids, as_of=None):
    ids = [value for value in organization_ids if value is not None]
    if not ids:
        return {}
    try:
        from hr_structure.public import get_organization_evidence

        evidence = get_organization_evidence(
            tenant_id=tenant_id,
            organization_ids=ids,
            as_of=as_of or date.today(),
        )
    except Exception:  # HR02 unavailable must stay explicit and must not leak an internal id.
        return {str(value): "组织信息暂不可用" for value in ids}
    labels = {
        str(row.organization_id): row.short_name or row.name or "未命名组织"
        for row in evidence.rows
    }
    for value in ids:
        labels.setdefault(str(value), "组织信息暂不可用")
    return labels


def _engagement_options(tenant_id, *, include_draft=False):
    statuses = list(_ACTIVE_ENGAGEMENT_STATUSES)
    if include_draft:
        statuses.append("DRAFT")
    rows = (
        HrExternalEngagement.objects.filter(tenant_id=tenant_id, status__in=statuses)
        .select_related("external_profile_id__person_id", "category_id")
        .order_by("external_profile_id__person_id__legal_name", "-start_at")
    )
    return [
        {
            "id": str(row.id),
            "label": f"{row.external_profile_id.person_id.legal_name} · {row.engagement_no}",
            "person_name": row.external_profile_id.person_id.legal_name,
            "engagement_no": row.engagement_no,
            "status_label": engagement_status_label(row.status),
            "start_at": row.start_at,
            "end_at": row.end_at,
            "owner_org_id": row.host_organization_id,
        }
        for row in rows
    ]


def external_teachers_home(request):
    """HR08-01 外聘教师库列表（人才库）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.profile.view")):
        raise PermissionDenied("PERMISSION_DENIED")
    _ensure_categories(tenant_id)

    def _int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    spec = ProfileFilterSpec(
        tenant_id=tenant_id,
        keyword=request.GET.get("keyword", ""),
        category_code=request.GET.get("category", ""),
        source_organization=request.GET.get("source_organization", ""),
        industry_domain=request.GET.get("industry_domain", ""),
        professional_title=request.GET.get("professional_title", ""),
        skill_level=request.GET.get("skill_level", ""),
        pool_status=request.GET.get("pool_status", ""),
        page=_int(request.GET.get("page"), 1),
        page_size=_int(request.GET.get("page_size"), 50),
    )
    total, items = list_external_profiles(spec)

    eng_active = HrExternalEngagement.objects.filter(
        tenant_id=tenant_id, status__in=_ACTIVE_ENGAGEMENT_STATUSES
    ).values_list("external_profile_id", flat=True).distinct()
    engaged_count = len(set(eng_active))
    industry_count = HrExternalTeacherProfile.objects.filter(
        tenant_id=tenant_id, primary_category__code__in=["INDUSTRY_PROFESSOR", "INDUSTRY_ADJUNCT", "SKILL_MASTER"]
    ).count()
    pending_hiring_count = HrExternalHiringCase.objects.filter(tenant_id=tenant_id).exclude(
        status__in=["ACTIVATED", "REJECTED", "WITHDRAWN", "CANCELLED"]
    ).count()
    today = date.today()
    expiring_15_count = HrExternalEngagement.objects.filter(
        tenant_id=tenant_id,
        status__in=_ACTIVE_ENGAGEMENT_STATUSES,
        end_at__gte=today,
        end_at__lte=today + timedelta(days=15),
    ).count()
    risk_count = HrExternalTeacherProfile.objects.filter(tenant_id=tenant_id).filter(
        ~Q(identity_verification_status="VERIFIED") | ~Q(ethics_status="PASS")
    ).count()

    for item in items:
        item["poolStatusLabel"] = pool_status_label(item["poolStatus"])
        item["engagementStatusLabel"] = engagement_status_label(item["currentEngagementStatus"])
    context = {
        **_workspace_context(request, "home"),
        "page_title": "外聘教师库",
        "total": total,
        "items": items,
        "engaged_count": engaged_count,
        "industry_count": industry_count,
        "pending_hiring_count": pending_hiring_count,
        "expiring_15_count": expiring_15_count,
        "risk_count": risk_count,
        "pool_status": spec.pool_status,
        "categories": CategoryService().list_categories(tenant_id),
    }
    return render(request, "hr_external/external_teacher_list.html", context)


def external_teacher_pool(request):
    """候选池（§24.1 pool 路由）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.profile.view")):
        raise PermissionDenied("PERMISSION_DENIED")
    _ensure_categories(tenant_id)

    spec = ProfileFilterSpec(
        tenant_id=tenant_id,
        pool_status=request.GET.get("pool_status", ""),
        keyword=request.GET.get("keyword", ""),
        page=1,
        page_size=100,
    )
    total, items = list_external_profiles(spec)
    for item in items:
        item["poolStatusLabel"] = pool_status_label(item["poolStatus"])
    return render(
        request,
        "hr_external/external_teacher_pool.html",
        {
            **_workspace_context(request, "pool"),
            "page_title": "候选池",
            "total": total,
            "items": items,
        },
    )


def external_teacher_profile(request, profile_id):
    """Profile 详情（§24.4）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.profile.view")):
        raise PermissionDenied("PERMISSION_DENIED")

    profile = get_object_or_404(
        HrExternalTeacherProfile.objects.select_related("person_id", "primary_category"),
        tenant_id=tenant_id,
        id=profile_id,
    )
    engagements = list(
        profile.engagements.filter(tenant_id=tenant_id)
        .select_related("category_id")
        .order_by("-start_at")
    )
    org_labels = _organization_labels(
        tenant_id, [engagement.host_organization_id for engagement in engagements]
    )
    engagement_rows = [
        {
            "engagement_no": engagement.engagement_no,
            "category_name": engagement.category_id.name or engagement.category_id.code,
            "organization_name": org_labels[str(engagement.host_organization_id)],
            "start_at": engagement.start_at,
            "end_at": engagement.end_at,
            "status_label": engagement_status_label(engagement.status),
        }
        for engagement in engagements
    ]
    return render(
        request,
        "hr_external/external_teacher_profile.html",
        {
            **_workspace_context(request, "home"),
            "page_title": f"外聘档案 · {profile.person_id.legal_name}",
            "profile": profile,
            "engagements": engagement_rows,
            "pool_status_label": pool_status_label(profile.candidate_pool_status),
            "engagement_status_label": engagement_status_label(profile.current_engagement_status),
            "ethics_status_label": ethics_status_label(profile.ethics_status),
            "identity_status_label": identity_verification_label(profile.identity_verification_status),
        },
    )


def industry_home(request):
    """HR08-02 产业教授与技能大师首页（§27.1）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.industry.view")):
        raise PermissionDenied("PERMISSION_DENIED")
    _ensure_categories(tenant_id)

    profiles = list(
        HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id,
            primary_category__code__in=[
                "INDUSTRY_PROFESSOR",
                "INDUSTRY_ADJUNCT",
                "SKILL_MASTER",
                "INDUSTRY_MENTOR",
            ],
        )
        .select_related("person_id", "primary_category", "industry_profile")
        .prefetch_related("engagements")
        .order_by("-updated_at")[:100]
    )
    workspaces = list(HrExternalWorkspace.objects.filter(tenant_id=tenant_id).order_by("-updated_at")[:50])
    workspace_orgs = _organization_labels(
        tenant_id, [workspace.organization_id for workspace in workspaces]
    )
    workspace_rows = [
        {
            "name": workspace.name,
            "type_label": _WORKSPACE_TYPE_LABELS.get(workspace.workspace_type, workspace.workspace_type),
            "organization_name": workspace_orgs[str(workspace.organization_id)],
            "start_at": workspace.start_at,
            "end_at": workspace.end_at,
            "status_label": _WORKSPACE_STATUS_LABELS.get(workspace.status, workspace.status),
        }
        for workspace in workspaces
    ]
    context = {
        **_workspace_context(request, "industry"),
        "page_title": "产业教授与技能大师",
        "items": profiles,
        "workspaces": workspace_rows,
    }
    return render(request, "hr_external/industry_home.html", context)


def industry_engagement_detail(request, engagement_id):
    """产业专家详情页（§27.1）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.industry.view")):
        raise PermissionDenied("PERMISSION_DENIED")

    eng = get_object_or_404(
        HrExternalEngagement.objects.select_related(
            "external_profile_id", "external_profile_id__person_id", "category_id"
        ),
        tenant_id=tenant_id,
        id=engagement_id,
    )
    ind = HrExternalIndustryProfile.objects.filter(
        tenant_id=tenant_id, profile_id=eng.external_profile_id
    ).first()
    contributions = HrExternalContribution.objects.filter(
        tenant_id=tenant_id, engagement_id=eng
    ).order_by("-updated_at")
    contribution_rows = [
        {
            "title": item.title,
            "type_label": _CONTRIBUTION_TYPE_LABELS.get(item.contribution_type, item.contribution_type),
            "period": item.period,
            "verification_label": contribution_verification_label(item.verification_status),
            "status_label": _CONTRIBUTION_STATUS_LABELS.get(item.status, item.status),
        }
        for item in contributions
    ]
    return render(
        request,
        "hr_external/industry_engagement_detail.html",
        {
            **_workspace_context(request, "industry"),
            "page_title": f"产业专家 · {eng.external_profile_id.person_id.legal_name}",
            "eng": eng,
            "industry_profile": ind,
            "contributions": contribution_rows,
            "engagement_status_label": engagement_status_label(eng.status),
        },
    )


def hiring_home(request):
    """HR08-03 聘用审批列表（§32.2）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.hiring.review")):
        raise PermissionDenied("PERMISSION_DENIED")

    status = request.GET.get("status", "")
    qs = HrExternalHiringCase.objects.filter(tenant_id=tenant_id).select_related(
        "category_id", "proposed_person_id"
    )
    if status:
        qs = qs.filter(status=status)
    cases = list(qs.order_by("-updated_at")[:200])
    org_labels = _organization_labels(tenant_id, [case.request_org_id for case in cases])
    case_rows = [
        {
            "id": case.id,
            "case_no": case.case_no,
            "person_name": case.proposed_person_id.legal_name if case.proposed_person_id else "尚未指定",
            "category_name": case.category_id.name or case.category_id.code,
            "purpose": case.purpose,
            "organization_name": org_labels[str(case.request_org_id)],
            "requested_start": case.requested_start,
            "status_label": _HIRING_STATUS_LABELS.get(case.status, case.status),
        }
        for case in cases
    ]

    counts = {
        "draft": qs.filter(status="DRAFT").count(),
        "in_review": qs.filter(status__in=["SUBMITTED", "UNDER_COLLEGE_REVIEW", "UNDER_HR_REVIEW", "UNDER_SCHOOL_APPROVAL"]).count(),
        "approved": qs.filter(status="APPROVED").count(),
        "activated": qs.filter(status="ACTIVATED").count(),
    }
    return render(
        request,
        "hr_external/hiring_list.html",
        {
            **_workspace_context(request, "hiring"),
            "page_title": "聘用审批",
            "cases": case_rows,
            "counts": counts,
            "current_status": status,
            "profiles": list(
                HrExternalTeacherProfile.objects.filter(tenant_id=tenant_id)
                .select_related("person_id", "primary_category")
                .order_by("person_id__legal_name")[:300]
            ),
            "categories": CategoryService().list_categories(tenant_id),
        },
    )


def hiring_detail(request, case_id):
    """聘用审批详情（full-page，§76）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.hiring.review")):
        raise PermissionDenied("PERMISSION_DENIED")

    case = get_object_or_404(
        HrExternalHiringCase.objects.select_related("category_id", "proposed_person_id"),
        tenant_id=tenant_id,
        id=case_id,
    )
    profile = HrExternalTeacherProfile.objects.filter(
        tenant_id=tenant_id, person_id_id=case.proposed_person_id_id
    ).first()
    compliance = None
    if profile is not None:
        compliance = ComplianceService().run_checks(
            tenant_id=tenant_id, case=case, profile=profile, category=case.category_id
        )
    org_label = _organization_labels(tenant_id, [case.request_org_id]).get(
        str(case.request_org_id), "组织信息暂不可用"
    )
    return render(
        request,
        "hr_external/hiring_detail.html",
        {
            **_workspace_context(request, "hiring"),
            "page_title": f"聘用审批 · {case.case_no}",
            "case": case,
            "profile": profile,
            "compliance": compliance,
            "request_org_label": org_label,
            "case_status_label": _HIRING_STATUS_LABELS.get(case.status, case.status),
        },
    )


def tasks_home(request):
    """HR08-04 教学与服务任务矩阵（§54）。"""
    from hr_external.models import HrExternalServiceTask, HrExternalWorkloadRecord

    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.task.view")):
        raise PermissionDenied("PERMISSION_DENIED")

    status = request.GET.get("status", "")
    qs = HrExternalServiceTask.objects.filter(tenant_id=tenant_id).select_related(
        "engagement_id", "engagement_id__external_profile_id", "engagement_id__external_profile_id__person_id"
    )
    if status:
        qs = qs.filter(status=status)
    tasks = list(qs.order_by("-updated_at")[:200])
    task_rows = [
        {
            "person_name": task.engagement_id.external_profile_id.person_id.legal_name,
            "engagement_no": task.engagement_id.engagement_no,
            "task_type_label": _TASK_TYPE_LABELS.get(task.task_type, task.task_type),
            "title": task.title,
            "source_label": _SOURCE_LABELS.get(task.source_domain, task.source_domain),
            "planned_quantity": task.planned_quantity,
            "planned_unit": task.planned_unit,
            "planned_start": task.planned_start,
            "planned_end": task.planned_end,
            "status_label": task_status_label(task.status),
        }
        for task in tasks
    ]

    counts = {
        "in_progress": qs.filter(status__in=["ASSIGNED", "ACCEPTED", "IN_PROGRESS"]).count(),
        "under_review": qs.filter(status="UNDER_REVIEW").count(),
        "overdue": qs.filter(planned_end__lt=date.today(), status__in=["ASSIGNED", "ACCEPTED", "IN_PROGRESS"]).count(),
        "completed": qs.filter(status="COMPLETED").count(),
    }
    return render(
        request,
        "hr_external/tasks_home.html",
        {
            **_workspace_context(request, "tasks"),
            "page_title": "教学与服务任务",
            "tasks": task_rows,
            "counts": counts,
            "current_status": status,
            "engagement_options": _engagement_options(tenant_id),
        },
    )


def renewals_home(request):
    """HR08-05 续聘中心（§58.1）。"""
    from hr_external.models import HrExternalRenewalReview

    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.renewal.review")):
        raise PermissionDenied("PERMISSION_DENIED")

    reviews = list(HrExternalRenewalReview.objects.filter(tenant_id=tenant_id).select_related(
        "engagement_id", "engagement_id__external_profile_id", "engagement_id__external_profile_id__person_id"
    ).order_by("review_due_at")[:200])
    review_rows = [
        {
            "person_name": review.engagement_id.external_profile_id.person_id.legal_name,
            "engagement_no": review.engagement_id.engagement_no,
            "start_at": review.engagement_id.start_at,
            "end_at": review.engagement_id.end_at,
            "review_due_at": review.review_due_at,
            "status_label": renewal_status_label(review.status),
            "decision_label": _RENEWAL_DECISION_LABELS.get(review.decision, "尚未决策"),
        }
        for review in reviews
    ]
    return render(
        request,
        "hr_external/renewals_home.html",
        {
            **_workspace_context(request, "renewals"),
            "page_title": "续聘中心",
            "reviews": review_rows,
            "engagement_options": _engagement_options(tenant_id),
        },
    )


def exits_home(request):
    """HR08-05 退出中心（§58.1）。"""
    from hr_external.models import HrExternalExitCase

    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.exit.manage")):
        raise PermissionDenied("PERMISSION_DENIED")

    cases = list(HrExternalExitCase.objects.filter(tenant_id=tenant_id).select_related(
        "engagement_id", "engagement_id__external_profile_id", "engagement_id__external_profile_id__person_id"
    ).order_by("-updated_at")[:200])
    case_rows = [
        {
            "id": case.id,
            "person_name": case.engagement_id.external_profile_id.person_id.legal_name,
            "engagement_no": case.engagement_id.engagement_no,
            "exit_reason_label": exit_reason_label(case.exit_reason),
            "planned_end_at": case.planned_end_at,
            "actual_end_at": case.actual_end_at,
            "status_label": exit_status_label(case.status),
        }
        for case in cases
    ]
    return render(
        request,
        "hr_external/exits_home.html",
        {
            **_workspace_context(request, "exits"),
            "page_title": "退出中心",
            "cases": case_rows,
            "engagement_options": _engagement_options(tenant_id),
        },
    )
