"""
hr_recruitment/selectors/campaign.py

HR04-02 招聘控制台/列表只读查询（总册 9.2）。
数据口径从规范业务事件/状态计算，不从 UI Stage 名称反推（总册 1.5/24）。
"""

from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from hr_recruitment.constants import (
    ApplicationCanonicalStatus,
    CampaignStatus,
    RecruitmentPositionStatus,
)
from hr_recruitment.labels import (
    CAMPAIGN_STATUS_LABELS,
    POSITION_STATUS_LABELS,
    status_label,
)
from hr_recruitment.models import (
    HrJobApplication,
    HrRecruitmentCampaign,
    HrRecruitmentPosition,
)

# 招聘项目类型（展示层映射，不改机器字段）
CAMPAIGN_TYPE_LABELS = {
    "SINGLE_POSITION": "单岗位招聘",
    "MULTI_POSITION": "多岗位招聘",
    "HIGH_LEVEL_TALENT": "高层次人才引进",
    "DOCTORAL_SPECIAL": "博士专项",
    "EXTERNAL_EMPLOY": "编外聘用",
}


def console_summary(*, tenant_id, scope=None):
    """招聘控制台 5 KPI + 漏斗 + 超期岗位（总册 9.2；支持跨学院 scope）。"""
    from hr_recruitment.selectors.scope_utils import apply_org_scope

    campaigns = HrRecruitmentCampaign.objects.filter(tenant_id=tenant_id)
    positions = HrRecruitmentPosition.objects.filter(tenant_id=tenant_id)
    applications = HrJobApplication.objects.filter(tenant_id=tenant_id)
    if scope:
        campaigns = apply_org_scope(campaigns, scope, org_field="positions__organization_id").distinct()
        positions = apply_org_scope(positions, scope)
        applications = apply_org_scope(applications, scope, org_field="recruitment_position_id__organization_id")

    ongoing = campaigns.filter(
        status__in=[CampaignStatus.PUBLISHED, CampaignStatus.OPEN, CampaignStatus.RESULT_PROCESSING]
    ).count()
    open_positions = positions.filter(status=RecruitmentPositionStatus.OPEN).count()
    pending_qualification = applications.filter(
        canonical_status__in=[
            ApplicationCanonicalStatus.SUBMITTED,
            ApplicationCanonicalStatus.UNDER_REVIEW,
            ApplicationCanonicalStatus.RESUBMITTED,
        ]
    ).count()
    now = timezone.now()
    week_start = now - timezone.timedelta(days=7)
    from hr_recruitment.models import HrAssessmentEvent

    this_week_assessments = HrAssessmentEvent.objects.filter(
        tenant_id=tenant_id, event_date__gte=week_start.date()
    ).count()
    pending_proposed = applications.filter(
        canonical_status__in=[
            ApplicationCanonicalStatus.PROPOSED_HIRE,
            ApplicationCanonicalStatus.PUBLIC_NOTICE,
        ]
    ).count()

    # 漏斗：报名→资格→选拔→拟录用→录用
    funnel = {
        "submitted": applications.filter(
            canonical_status__in=[s for s in ApplicationCanonicalStatus.values]
        ).count(),
        "qualified": applications.filter(canonical_status__in=[
            ApplicationCanonicalStatus.QUALIFIED,
            ApplicationCanonicalStatus.ASSESSMENT_PENDING,
            ApplicationCanonicalStatus.ASSESSING,
            ApplicationCanonicalStatus.ASSESSMENT_PASSED,
            ApplicationCanonicalStatus.MEDICAL_PENDING,
            ApplicationCanonicalStatus.BACKGROUND_PENDING,
        ]).count(),
        "assessed": applications.filter(canonical_status__in=[
            ApplicationCanonicalStatus.ASSESSMENT_PASSED,
            ApplicationCanonicalStatus.MEDICAL_PENDING,
            ApplicationCanonicalStatus.BACKGROUND_PENDING,
        ]).count(),
        "proposed": applications.filter(canonical_status__in=[
            ApplicationCanonicalStatus.PROPOSED_HIRE,
            ApplicationCanonicalStatus.PUBLIC_NOTICE,
            ApplicationCanonicalStatus.OFFER_PENDING,
            ApplicationCanonicalStatus.OFFERED,
            ApplicationCanonicalStatus.OFFER_ACCEPTED,
        ]).count(),
        "hired": applications.filter(canonical_status=ApplicationCanonicalStatus.HANDOFF_TO_HR05).count(),
    }

    overdue_positions = positions.filter(
        status=RecruitmentPositionStatus.OPEN,
        campaign_id__application_close_at__lt=now,
    )[:20]

    return {
        "kpis": {
            "ongoing_campaigns": ongoing,
            "open_positions": open_positions,
            "pending_qualification": pending_qualification,
            "this_week_assessments": this_week_assessments,
            "pending_proposed": pending_proposed,
        },
        "funnel": funnel,
        "overdue_positions": [
            {
                "id": str(p.id),
                "post_catalog_name": p.post_catalog_name,
                "campaign_title": p.campaign_id.title if p.campaign_id else "",
                "application_close_at": (
                    p.campaign_id.application_close_at.isoformat()
                    if p.campaign_id and p.campaign_id.application_close_at
                    else None
                ),
            }
            for p in overdue_positions
        ],
    }


def list_campaigns(*, tenant_id, scope=None, status=None, page=1, page_size=20):
    qs = HrRecruitmentCampaign.objects.filter(tenant_id=tenant_id)
    if scope:
        from hr_recruitment.selectors.scope_utils import apply_org_scope

        qs = apply_org_scope(qs, scope, org_field="positions__organization_id").distinct()
    if status:
        qs = qs.filter(status=status)
    total = qs.count()
    qs = qs.order_by("-created_at")[(page - 1) * page_size : page * page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(c.id),
                "code": c.code,
                "title": c.title,
                "campaign_type": c.campaign_type,
                "campaignTypeLabel": CAMPAIGN_TYPE_LABELS.get(c.campaign_type, c.campaign_type),
                "status": c.status,
                "statusLabel": status_label(CAMPAIGN_STATUS_LABELS, c.status),
                "public_slug": c.public_slug,
                "application_open_at": c.application_open_at.isoformat() if c.application_open_at else None,
                "application_close_at": c.application_close_at.isoformat() if c.application_close_at else None,
                "position_count": c.positions.count(),
            }
            for c in qs
        ],
    }


def get_campaign(*, tenant_id, campaign_id):
    try:
        campaign = HrRecruitmentCampaign.objects.get(
            id=campaign_id, tenant_id=tenant_id
        )
    except HrRecruitmentCampaign.DoesNotExist:
        return None
    positions = HrRecruitmentPosition.objects.filter(
        tenant_id=tenant_id, campaign_id=campaign
    ).order_by("created_at")
    return {
        "id": str(campaign.id),
        "code": campaign.code,
        "title": campaign.title,
        "campaign_type": campaign.campaign_type,
        "campaignTypeLabel": CAMPAIGN_TYPE_LABELS.get(campaign.campaign_type, campaign.campaign_type),
        "status": campaign.status,
        "statusLabel": status_label(CAMPAIGN_STATUS_LABELS, campaign.status),
        "public_slug": campaign.public_slug,
        "application_open_at": campaign.application_open_at.isoformat() if campaign.application_open_at else None,
        "application_close_at": campaign.application_close_at.isoformat() if campaign.application_close_at else None,
        "timezone": campaign.timezone,
        "description": campaign.description,
        "positions": [
            {
                "id": str(p.id),
                "post_catalog_name": p.post_catalog_name,
                "organization_name": p.organization_name,
                "planned_headcount": p.planned_headcount,
                "reserved_headcount": p.reserved_headcount,
                "status": p.status,
                "statusLabel": status_label(POSITION_STATUS_LABELS, p.status),
                "position_id": p.position_id,
                "reservation_id": p.reservation_id,
            }
            for p in positions
        ],
    }
