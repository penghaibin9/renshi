"""
hr_external/views.py —— HR08 页面视图（S1 骨架 + S3 外聘教师库）。

页面：
- /hr/external-teachers/                    外聘教师库（HR08-01）
- /hr/external-teachers/pool/               候选池
- /hr/external-teachers/<profile_id>/       Profile 详情
"""

from datetime import date

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from hr_external.context import resolve_tenant_from_request
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


def _require_tenant(request):
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED")
    return tenant_id


def _ensure_categories(tenant_id):
    CategoryService().ensure_default_categories(tenant_id)


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
        tenant_id=tenant_id, status__in=["ACTIVE", "REVIEW_DUE", "RENEWAL_IN_PROGRESS", "SIGNED_WAITING_EFFECTIVE"]
    ).values_list("external_profile_id", flat=True).distinct()
    engaged_count = len(set(eng_active))
    industry_count = HrExternalTeacherProfile.objects.filter(
        tenant_id=tenant_id, primary_category__code__in=["INDUSTRY_PROFESSOR", "INDUSTRY_ADJUNCT", "SKILL_MASTER"]
    ).count()

    context = {
        "page_title": "外聘教师库",
        "total": total,
        "items": items,
        "engaged_count": engaged_count,
        "industry_count": industry_count,
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
    return render(
        request,
        "hr_external/external_teacher_pool.html",
        {"page_title": "候选池", "total": total, "items": items},
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
    engagements = profile.engagements.filter(tenant_id=tenant_id).order_by("-start_at")
    return render(
        request,
        "hr_external/external_teacher_profile.html",
        {
            "page_title": f"外聘档案 · {profile.person_id.legal_name}",
            "profile": profile,
            "engagements": engagements,
        },
    )


def industry_home(request):
    """HR08-02 产业教授与技能大师首页（§27.1）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.industry.view")):
        raise PermissionDenied("PERMISSION_DENIED")
    _ensure_categories(tenant_id)

    profiles = (
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
        .order_by("-updated_at")[:100]
    )
    workspaces = HrExternalWorkspace.objects.filter(tenant_id=tenant_id).order_by("-updated_at")[:50]
    context = {
        "page_title": "产业教授与技能大师",
        "items": profiles,
        "workspaces": workspaces,
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
    return render(
        request,
        "hr_external/industry_engagement_detail.html",
        {
            "page_title": f"产业专家 · {eng.external_profile_id.person_id.legal_name}",
            "eng": eng,
            "industry_profile": ind,
            "contributions": contributions,
        },
    )


def hiring_home(request):
    """HR08-03 聘用审批列表（§32.2）。"""
    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.hiring.review")):
        raise PermissionDenied("PERMISSION_DENIED")

    status = request.GET.get("status", "")
    qs = HrExternalHiringCase.objects.filter(tenant_id=tenant_id).select_related("category_id")
    if status:
        qs = qs.filter(status=status)
    cases = qs.order_by("-updated_at")[:200]

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
            "page_title": "聘用审批",
            "cases": cases,
            "counts": counts,
            "current_status": status,
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
    return render(
        request,
        "hr_external/hiring_detail.html",
        {
            "page_title": f"聘用审批 · {case.case_no}",
            "case": case,
            "profile": profile,
            "compliance": compliance,
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
    tasks = qs.order_by("-updated_at")[:200]

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
            "page_title": "教学与服务任务",
            "tasks": tasks,
            "counts": counts,
            "current_status": status,
        },
    )


def renewals_home(request):
    """HR08-05 续聘中心（§58.1）。"""
    from hr_external.models import HrExternalRenewalReview

    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.renewal.review")):
        raise PermissionDenied("PERMISSION_DENIED")

    reviews = HrExternalRenewalReview.objects.filter(tenant_id=tenant_id).select_related(
        "engagement_id", "engagement_id__external_profile_id", "engagement_id__external_profile_id__person_id"
    ).order_by("review_due_at")[:200]
    return render(
        request,
        "hr_external/renewals_home.html",
        {"page_title": "续聘中心", "reviews": reviews},
    )


def exits_home(request):
    """HR08-05 退出中心（§58.1）。"""
    from hr_external.models import HrExternalExitCase

    tenant_id = _require_tenant(request)
    if not (request.user.is_superuser or request.user.has_perm("hr08.exit.manage")):
        raise PermissionDenied("PERMISSION_DENIED")

    cases = HrExternalExitCase.objects.filter(tenant_id=tenant_id).select_related(
        "engagement_id", "engagement_id__external_profile_id", "engagement_id__external_profile_id__person_id"
    ).order_by("-updated_at")[:200]
    return render(
        request,
        "hr_external/exits_home.html",
        {"page_title": "退出中心", "cases": cases},
    )
