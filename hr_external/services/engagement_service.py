"""
hr_external/services/engagement_service.py —— Engagement 创建/状态转换守卫（S2，总册 §19/§20/§21/§43）。

关键不变量：
- tenant FK 一致性（person/profile/category 必须同 tenant）；
- 时间区间统一为 [start_at, end_at)；
- 同一 person 的有效 engagement 不得重叠；
- 创建时锁住 profile 行，避免“当前无 engagement”时两个并发事务同时插入；
- 状态机合法转换守卫；
- 正式状态写入必须锁行、校验 version，并在 ACTIVE 前执行 HR07 agreement gate。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.db import transaction
from django.db.models import Q

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


class AgreementGateBlocked(Exception):
    code = "EXTERNAL_AGREEMENT_REQUIRED"


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
    _OVERLAP_STATUSES = [
        ExternalEngagementStatus.ACTIVE,
        ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
        ExternalEngagementStatus.REVIEW_DUE,
        ExternalEngagementStatus.SUSPENDED,
    ]

    @staticmethod
    def validate_transition(current: str, target: str) -> bool:
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        return target in allowed

    @transaction.atomic
    def create_engagement(self, payload: EngagementCreateInput) -> HrExternalEngagement:
        import uuid as _uuid

        tenant_id = payload.tenant_id
        if not tenant_id:
            raise CrossTenantReference("tenant_id is required")

        # 锁 profile 作为 per-person 串行化锚点：即使当前 0 条 engagement，
        # 两个并发创建也会在同一 profile 行上排队，避免 read-then-insert race。
        try:
            profile = (
                HrExternalTeacherProfile.objects.select_for_update()
                .select_related("primary_category")
                .get(id=payload.profile_id, tenant_id=tenant_id)
            )
        except HrExternalTeacherProfile.DoesNotExist as exc:
            raise CrossTenantReference("profile not found inside tenant") from exc

        if str(profile.person_id_id) != str(payload.person_id):
            raise CrossTenantReference("profile/person identity mismatch")

        try:
            category = HrExternalCategory.objects.get(
                id=payload.category_id,
                tenant_id=tenant_id,
            )
        except HrExternalCategory.DoesNotExist as exc:
            raise CrossTenantReference("category not found inside tenant") from exc

        if payload.end_at and payload.start_at >= payload.end_at:
            raise InvalidEngagementState("EXTERNAL_ENGAGEMENT_DATES_INVALID")

        # 半开区间 [start,end) 重叠判定：
        # existing.end > new.start（或 existing 无结束）
        # 且 existing.start < new.end（若 new.end 有值）。
        overlap_qs = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id,
            person_id_id=payload.person_id,
            status__in=self._OVERLAP_STATUSES,
        ).filter(Q(end_at__isnull=True) | Q(end_at__gt=payload.start_at))
        if payload.end_at is not None:
            overlap_qs = overlap_qs.filter(start_at__lt=payload.end_at)

        if overlap_qs.exists():
            raise EngagementOverlap("person already has an overlapping active engagement")

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

    @transaction.atomic
    def transition(
        self,
        *,
        engagement_id,
        tenant_id: int,
        target_status: str,
        expected_version: Optional[int] = None,
        as_of: Optional[date] = None,
    ) -> HrExternalEngagement:
        """唯一正式状态写入口：tenant + 行锁 + version + agreement/effective gate。"""
        if not tenant_id:
            raise CrossTenantReference("tenant_id is required")

        engagement = (
            HrExternalEngagement.objects.select_for_update()
            .filter(id=engagement_id, tenant_id=tenant_id)
            .first()
        )
        if engagement is None:
            # 不区分“对象存在于别的 tenant”与“不存在”，防止越权枚举。
            raise CrossTenantReference("engagement not found inside tenant")

        if expected_version is not None and engagement.version != expected_version:
            raise InvalidEngagementState("VERSION_CONFLICT")

        if not self.validate_transition(engagement.status, target_status):
            raise InvalidEngagementState(
                f"invalid engagement transition: {engagement.status} -> {target_status}"
            )

        if target_status == ExternalEngagementStatus.ACTIVE:
            if not self.agreement_gate_passed(engagement):
                raise AgreementGateBlocked("agreement is not ready for activation")

            effective_day = as_of or date.today()
            if engagement.start_at > effective_day:
                raise InvalidEngagementState("EXTERNAL_ENGAGEMENT_NOT_EFFECTIVE_YET")
            if engagement.end_at is not None and engagement.end_at <= effective_day:
                raise InvalidEngagementState("EXTERNAL_ENGAGEMENT_ALREADY_ENDED")

        engagement.status = target_status
        engagement.version += 1
        engagement.save(update_fields=["status", "version", "updated_at"])
        return engagement

    def set_agreement_status(
        self,
        engagement: HrExternalEngagement,
        provider_status: str,
        *,
        tenant_id: int,
    ) -> None:
        """从 HR07 Provider 结果投影 agreement_status；显式 tenant 防止跨校对象写入。"""
        if getattr(engagement, "tenant_id", None) != tenant_id:
            raise CrossTenantReference("engagement tenant mismatch")
        valid = {c.value for c in AgreementProviderStatus}
        engagement.agreement_status = (
            provider_status
            if provider_status in valid
            else AgreementProviderStatus.UNAVAILABLE.value
        )
        engagement.save(update_fields=["agreement_status", "updated_at"])

    def agreement_gate_passed(self, engagement: HrExternalEngagement) -> bool:
        """Agreement gate（§42/§93）：激活前协议就绪。"""
        if engagement.agreement_requirement == AgreementRequirement.NOT_REQUIRED:
            return True
        if (
            engagement.agreement_requirement
            == AgreementRequirement.REQUIRED_BEFORE_ACTIVATION
        ):
            return engagement.agreement_status in (
                AgreementProviderStatus.SIGNED.value,
                AgreementProviderStatus.ACTIVE.value,
            )
        return True
