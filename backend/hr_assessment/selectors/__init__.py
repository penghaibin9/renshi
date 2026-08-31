"""
hr_assessment/selectors/ —— 查询层（遵循 hr_staff 的 Selector 模式）。

独立查询逻辑，不混合 API/serialization。每个 Selector 接收 frozen context。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.db.models import QuerySet

from hr_assessment.context import HrAssessmentRequestContext
from hr_assessment.models.policy import HrAssessmentPolicyPack, HrAssessmentPolicyVersion, HrRatingScaleVersion, HrIndicatorDefinition


@dataclass(frozen=True)
class SelectorContext:
    ctx: HrAssessmentRequestContext
    tenant_id: int

    def __post_init__(self):
        if not self.tenant_id:
            raise ValueError("tenant_id required")

    @classmethod
    def from_request_context(cls, ctx: HrAssessmentRequestContext) -> "SelectorContext":
        return cls(ctx=ctx, tenant_id=ctx.tenant_id)


class PolicySelector:
    def list_policy_packs(self, sc: SelectorContext) -> QuerySet[HrAssessmentPolicyPack]:
        return HrAssessmentPolicyPack.objects.filter(tenant_id=sc.tenant_id).order_by("code")

    def list_policy_versions(self, sc: SelectorContext, pack_id: int) -> QuerySet[HrAssessmentPolicyVersion]:
        return HrAssessmentPolicyVersion.objects.filter(
            tenant_id=sc.tenant_id, policy_pack_id=pack_id,
        ).order_by("-version_no")

    def resolve_active_version(self, sc: SelectorContext) -> QuerySet[HrAssessmentPolicyVersion]:
        today = sc.ctx.today()
        return HrAssessmentPolicyVersion.objects.filter(
            tenant_id=sc.tenant_id, status="PUBLISHED",
            effective_from__lte=today,
        ).exclude(effective_to__lt=today).order_by("-version_no")


class IndicatorSelector:
    def list_active_indicators(self, sc: SelectorContext) -> QuerySet[HrIndicatorDefinition]:
        return HrIndicatorDefinition.objects.filter(
            tenant_id=sc.tenant_id, is_active=True,
        ).order_by("dimension", "code")


class RatingScaleSelector:
    def list_scales(self, sc: SelectorContext) -> QuerySet[HrRatingScaleVersion]:
        return HrRatingScaleVersion.objects.filter(
            tenant_id=sc.tenant_id, status="PUBLISHED",
        ).order_by("-version_no")
