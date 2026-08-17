"""
hr_external/providers/dashboard.py —— HR08 工作台指标 Provider（HR01 消费，总册 §132/§102）。

对齐 hr_control_center.providers.base：
- 禁止 try/except pass / return 0（UNAVAILABLE 而不是吞掉）；
- 每个指标带 max_stale_seconds / data_basis / authority_mode；
- scope 裁剪：COLLEGE 时只统计该学院 host_organization_id 的聘期。
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from hr_external.constants import ExternalEngagementStatus
from hr_external.models import (
    HrExternalEngagement,
    HrExternalRenewalReview,
    HrExternalServiceTask,
    HrExternalTeacherProfile,
    HrExternalWorkloadRecord,
)

PROVIDER_KEY = "hr08.dashboard"
DEFINITION_VERSION = "hr08.dashboard.1"

_ACTIVE = [
    ExternalEngagementStatus.ACTIVE,
    ExternalEngagementStatus.REVIEW_DUE,
    ExternalEngagementStatus.RENEWAL_IN_PROGRESS,
    ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
    ExternalEngagementStatus.SUSPENDED,
]
_TASK_OVERDUE_STATUSES = ["ASSIGNED", "ACCEPTED", "IN_PROGRESS"]


def hr08_dashboard_metrics(
    *,
    tenant_id: int,
    ctx=None,
) -> dict:
    """返回 HR08 工作台指标（status=OK；数据可用性由 provider 层保证）。"""
    scope_org = getattr(ctx.scope, "org_id", None) if ctx else None
    is_college = (ctx.scope.scope_type in ("COLLEGE", "ORGANIZATION")) if ctx else False

    def _org_filter(qs):
        if is_college and scope_org:
            return qs.filter(host_organization_id=scope_org)
        return qs

    eng_qs = _org_filter(HrExternalEngagement.objects.filter(tenant_id=tenant_id))
    # 学校时区今天（ctx 携带 school_timezone；无 ctx 时退化为服务器本地时区）
    today = ctx.today() if ctx and hasattr(ctx, "today") else timezone.localdate()

    active_engagements = eng_qs.filter(status__in=_ACTIVE).count()
    expiring = (
        eng_qs.filter(
            status__in=_ACTIVE,
            end_at__lte=today + timedelta(days=90),
            end_at__gte=today,
        ).count()
    )

    task_qs = HrExternalServiceTask.objects.filter(tenant_id=tenant_id)
    if is_college and scope_org:
        task_qs = task_qs.filter(owner_org_id=scope_org)
    tasks_overdue = task_qs.filter(
        planned_end__lt=today, status__in=_TASK_OVERDUE_STATUSES
    ).count()

    workload_qs = HrExternalWorkloadRecord.objects.filter(
        tenant_id=tenant_id, verification_status="UNVERIFIED"
    )
    if is_college and scope_org:
        workload_qs = workload_qs.filter(engagement_id__host_organization_id=scope_org)
    workload_unverified = workload_qs.count()

    industry_count = HrExternalTeacherProfile.objects.filter(
        tenant_id=tenant_id,
        primary_category__code__in=[
            "INDUSTRY_PROFESSOR",
            "INDUSTRY_ADJUNCT",
            "SKILL_MASTER",
            "INDUSTRY_MENTOR",
        ],
    ).count()

    renewals_qs = HrExternalRenewalReview.objects.filter(
        tenant_id=tenant_id,
        status__in=["DRAFT", "IN_REVIEW"],
        review_due_at__lte=today + timedelta(days=30),
    )
    if is_college and scope_org:
        renewals_qs = renewals_qs.filter(engagement_id__host_organization_id=scope_org)
    renewals_due = renewals_qs.count()

    return {
        "activeEngagements": active_engagements,
        "engagementsExpiring90d": expiring,
        "tasksOverdue": tasks_overdue,
        "workloadUnverified": workload_unverified,
        "industryExperts": industry_count,
        "renewalsDue30d": renewals_due,
        "sourceUpdatedAt": timezone.now().isoformat(),
        "maxStaleSeconds": 60,
        "hardExpireSeconds": 300,
        "dataBasis": "HR08_AUTHORITY",
        "authorityMode": ctx.authority_mode if ctx else "LEGACY_EMPLOYEE_TAG_ONLY",
        "definitionVersion": DEFINITION_VERSION,
    }


def hr08_active_engagements(
    *,
    tenant_id: int,
    ctx=None,
):
    """HR01 消费：活跃外聘聘期数。"""
    data = hr08_dashboard_metrics(tenant_id=tenant_id, ctx=ctx)
    return {
        "providerKey": PROVIDER_KEY,
        "metricKey": "hr08_active_engagements",
        "value": data["activeEngagements"],
        **data,
    }


def hr08_engagements_expiring(
    *,
    tenant_id: int,
    ctx=None,
):
    data = hr08_dashboard_metrics(tenant_id=tenant_id, ctx=ctx)
    return {
        "providerKey": PROVIDER_KEY,
        "metricKey": "hr08_engagements_expiring",
        "value": data["engagementsExpiring90d"],
        **data,
    }


def hr08_tasks_overdue(
    *,
    tenant_id: int,
    ctx=None,
):
    data = hr08_dashboard_metrics(tenant_id=tenant_id, ctx=ctx)
    return {
        "providerKey": PROVIDER_KEY,
        "metricKey": "hr08_tasks_overdue",
        "value": data["tasksOverdue"],
        **data,
    }


def hr08_industry_experts(
    *,
    tenant_id: int,
    ctx=None,
):
    data = hr08_dashboard_metrics(tenant_id=tenant_id, ctx=ctx)
    return {
        "providerKey": PROVIDER_KEY,
        "metricKey": "hr08_industry_experts",
        "value": data["industryExperts"],
        **data,
    }
