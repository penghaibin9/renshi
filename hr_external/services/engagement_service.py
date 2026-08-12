"""
hr_external/services/engagement_service.py —— Engagement 创建/状态转换守卫（S2，总册 §19/§20/§21/§43）。

S2 范围：模型落库后的基础不变量：
- tenant FK 一致性（person/profile/category 必须同 tenant）；
- start_at < end_at（半开区间，§7）；
- 重叠检测（同一 person 的 active engagement，§38）；workload cap 校验（service 层，S5 完整）；
- 状态机合法转换守卫（DRAFT→UNDER_REVIEW→...，§20）；
- activation 流程在 S5（HR08-03）完整实现（lock case → revalidate → HR07 gate → create → event）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction

from hr_external.constants import (
    AgreementProviderStatus,
    AgreementRequirement,
    ExternalEngagementStatus,
)
from hr_external.models import (
    HrExternalCategory,
    HrExternalEngagement,
    HrExternalEngagementAssignment,
    HrExternalTeacherProfile,
)


class EngagementOverlap(Exception):
    code = "EXTERNAL_ENGAGEMENT_OVERLAP"


class CrossTenantReference(Exception):
    code = "CROSS_TENANT_REFERENCE"


class InvalidEngagementState(Exception):
    code = "VERSION_CONFLICT"


# 状态机合法转换（§20）。异常态（RETURNED/REJECTED/CANCELLED/SUSPENDED/BLOCKED）由 service 守卫。
_ALLOWED_TRANSITIONS = {
    ExternalEngagementStatus.DRAFT: {
        ExternalEngagementStatus.UNDER_REVIEW,
        ExternalEngagementStatus.CANCELLED,
    },
    ExternalEngagementStatus.UNDER_REVIEW: {
        ExternalEngagementStatus.APPROVED,
        ExternalEngagementStatus.RETURNED,
        ExternalEngagementStatus.REJECTED,
        ExternalEngagementStatus.CANCELLED,
    },
    ExternalEngagementStatus.APPROVED: {
        ExternalEngagementStatus.WAITING_AGREEMENT,
        ExternalEngagementStatus.CANCELLED,
    },
    ExternalEngagementStatus.WAITING_AGREEMENT: {
        ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
        ExternalEngagementStatus.RETURNED,
        ExternalEngagementStatus.CANCELLED,
    },
    ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE: {
        ExternalEngagementStatus.ACTIVE,
        ExternalEngagementStatus.CANCELLED,
    },
    ExternalEngagementStatus.ACTIVE: {
        ExternalEngagementStatus.REVIEW_DUE,
        ExternalEngagementStatus.SUSPENDED,
        ExternalEngagementStatus.EXITING,
        ExternalEngagementStatus.ENDED,
    },
    ExternalEngagementStatus.SUSPENDED: {ExternalEngagementStatus.ACTIVE},
    ExternalEngagementStatus.REVIEW_DUE: {
        ExternalEngagementStatus.RENEWAL_IN_PROGRESS,
        ExternalEngagementStatus.EXITING,
        ExternalEngagementStatus.ENDED,
    },
    ExternalEngagementStatus.RENEWAL_IN_PROGRESS: {
        ExternalEngagementStatus.ACTIVE,
        ExternalEngagementStatus.EXITING,
    },
    ExternalEngagementStatus.EXITING: {ExternalEngagementStatus.ENDED},
    ExternalEngagementStatus.ENDED: {ExternalEngagementStatus.ARCHIVED},
}


@dataclass
class EngagementCreateInput:
    tenant_id: int
    person_id: object
    profile_id: object
    category_id: object
    host_organization_id: int
    start_at: date
    end_at: Optional[date] = None
    review_at: Optional[date] = None
    purpose: str = ""
    source_type: str = "COLLEGE_RECOMMENDATION"
    workload_cap: Optional[float] = None
    engagement_no: Optional[str] = None


class EngagementService:
    @staticmethod
    def validate_transition(current: str, target: str) -> bool:
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        return target in allowed

    @transaction.atomic
    def create_engagement(self, payload: EngagementCreateInput) -> HrExternalEngagement:
        import uuid as _uuid

        tenant_id = payload.tenant_id
        profile = HrExternalTeacherProfile.objects.select_related("primary_category").get(
            id=payload.profile_id
        )
        if profile.tenant_id != tenant_id or str(profile.person_id_id) != str(payload.person_id):
            raise CrossTenantReference("profile/person tenant or identity mismatch")

        category = HrExternalCategory.objects.get(id=payload.category_id)
        if category.tenant_id != tenant_id:
            raise CrossTenantReference("category tenant mismatch")

        if payload.end_at and payload.start_at >= payload.end_at:
            raise InvalidEngagementState("EXTERNAL_ENGAGEMENT_DATES_INVALID")

        # 重叠检测（§38）+ 并发防护：锁住该 person 的 active 行，read-then-write 竞态下
        # 第二个事务等锁后必然看到第一个已提交的 engagement（A9）。
        HrExternalEngagement.objects.select_for_update().filter(
            tenant_id=tenant_id,
            person_id_id=payload.person_id,
            status__in=[
                ExternalEngagementStatus.ACTIVE,
                ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
                ExternalEngagementStatus.REVIEW_DUE,
                ExternalEngagementStatus.SUSPENDED,
            ],
        ).exists()
        overlapping = (
            HrExternalEngagement.objects.filter(
                tenant_id=tenant_id,
                person_id_id=payload.person_id,
                status__in=[
                    ExternalEngagementStatus.ACTIVE,
                    ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
                    ExternalEngagementStatus.REVIEW_DUE,
                    ExternalEngagementStatus.SUSPENDED,
                ],
            )
            .exclude(end_at__lt=payload.start_at)
            .exists()
        )
        if overlapping:
            raise EngagementOverlap("person already has an overlapping active engagement")

        # 默认编号：带唯一后缀（S5 正式编号规则替换为 tenant-scoped sequence）
        engagement_no = payload.engagement_no or (
            f"E{payload.start_at:%Y%m%d}{_uuid.uuid4().hex[:6].upper()}"
        )
        return HrExternalEngagement.objects.create(
            tenant_id=tenant_id,
            engagement_no=engagement_no,
            person_id_id=payload.person_id,
            external_profile_id=profile,
            category_id=category,
            purpose=payload.purpose,
            source_type=payload.source_type,
            host_organization_id=payload.host_organization_id,
            start_at=payload.start_at,
            end_at=payload.end_at,
            review_at=payload.review_at,
            workload_cap=payload.workload_cap,
            agreement_requirement=category.agreement_requirement,
            agreement_status=AgreementProviderStatus.UNAVAILABLE.value,
            status=ExternalEngagementStatus.DRAFT,
        )

    def set_agreement_status(self, engagement: HrExternalEngagement, provider_status: str) -> None:
        """从 HR07 Provider 结果投影 agreement_status（§7；不建第二套协议表）。"""
        valid = {c.value for c in AgreementProviderStatus}
        engagement.agreement_status = provider_status if provider_status in valid else AgreementProviderStatus.UNAVAILABLE.value
        engagement.save(update_fields=["agreement_status", "updated_at"])

    def agreement_gate_passed(self, engagement: HrExternalEngagement) -> bool:
        """Agreement gate（§42/§93）：激活前协议就绪。"""
        if engagement.agreement_requirement == AgreementRequirement.NOT_REQUIRED:
            return True
        if engagement.agreement_requirement == AgreementRequirement.REQUIRED_BEFORE_ACTIVATION:
            return engagement.agreement_status in (
                AgreementProviderStatus.SIGNED.value,
                AgreementProviderStatus.ACTIVE.value,
            )
        return True
