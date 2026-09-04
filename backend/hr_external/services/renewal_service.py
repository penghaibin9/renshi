"""
hr_external/services/renewal_service.py —— 续聘（S8，总册 §58-62）。

- RenewalReview：到期评估（§59），决策（§60）；
- 续聘不是改 end_at（§61/§138.11）：RENEW → 创建新 Engagement（完整走 S5 审批链）；
- CONVERT_TO_REGULAR_HR_PROCESS：转正式员工走 HR04/HR05/HR03 正式链（§62），不直接改 worker_kind；
- 到期只 Review 不自动续（§138.11）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_external.constants import (
    ExternalEngagementStatus,
    RenewalDecision,
    RenewalReviewStatus,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalRenewalReview,
)


class RenewalAlreadyExists(Exception):
    code = "EXTERNAL_RENEWAL_ALREADY_EXISTS"


class RenewalStateConflict(Exception):
    code = "VERSION_CONFLICT"


class RenewalService:
    @transaction.atomic
    def create_review(
        self,
        *,
        tenant_id: int,
        engagement_id,
        review_due_at: date,
        task_completion_summary: str = "",
        quality_summary: str = "",
        agreement_status: str = "",
        access_summary: str = "",
        requester_org_opinion: str = "",
        person_willingness: str = "",
    ) -> HrExternalRenewalReview:
        eng = HrExternalEngagement.objects.select_for_update().filter(
            tenant_id=tenant_id, id=engagement_id
        ).first()
        if eng is None:
            raise RenewalStateConflict("EXTERNAL_ENGAGEMENT_NOT_FOUND")

        review = HrExternalRenewalReview.objects.create(
            tenant_id=tenant_id,
            engagement_id=eng,
            review_due_at=review_due_at,
            task_completion_summary=task_completion_summary,
            quality_summary=quality_summary,
            agreement_status=agreement_status,
            access_summary=access_summary,
            requester_org_opinion=requester_org_opinion,
            person_willingness=person_willingness,
            status=RenewalReviewStatus.DRAFT,
        )
        # 触发 Engagement → REVIEW_DUE（§20）
        if eng.status in (ExternalEngagementStatus.ACTIVE, ExternalEngagementStatus.REVIEW_DUE):
            eng.status = ExternalEngagementStatus.REVIEW_DUE
            eng.version += 1
            eng.save(update_fields=["status", "version", "updated_at"])
        return review

    @transaction.atomic
    def decide(
        self,
        review: HrExternalRenewalReview,
        *,
        tenant_id: int,
        decision: str,
        decided_by=None,
        next_start: Optional[date] = None,
        next_end: Optional[date] = None,
        next_category_id=None,
        next_host_org_id=None,
    ) -> str:
        """做出续聘决策（§60）。RENEW 创建新 Engagement（保持聘期边界，§61）。

        CHANGE_CATEGORY → next_category_id 指定新类别；
        CHANGE_HOST_ORG → next_host_org_id 指定新主办学院。
        未指定时沿用原值（RENEW/RENEW_WITH_CHANGES 默认语义）。
        """
        review = (
            HrExternalRenewalReview.objects.select_for_update()
            .select_related("engagement_id", "engagement_id__category_id")
            .filter(tenant_id=tenant_id, id=getattr(review, "pk", None))
            .first()
        )
        if review is None:
            raise RenewalStateConflict("EXTERNAL_RENEWAL_REVIEW_NOT_FOUND")
        # The API historically advanced DRAFT immediately before deciding. Keep
        # that HTTP behaviour, but perform both writes under this one tenant lock.
        if review.status == RenewalReviewStatus.DRAFT:
            review.status = RenewalReviewStatus.IN_REVIEW
        if review.status != RenewalReviewStatus.IN_REVIEW:
            raise RenewalStateConflict("review not in review status")
        if decision not in {d.value for d in RenewalDecision}:
            raise RenewalStateConflict("invalid renewal decision")

        review.decision = decision
        review.status = RenewalReviewStatus.DECIDED
        review.decided_by = decided_by
        review.decided_at = timezone.now()

        if decision in (
            RenewalDecision.RENEW,
            RenewalDecision.RENEW_WITH_CHANGES,
            RenewalDecision.CHANGE_CATEGORY,
            RenewalDecision.CHANGE_HOST_ORG,
        ):
            import uuid as _uuid

            eng = HrExternalEngagement.objects.select_for_update().get(
                tenant_id=tenant_id, id=review.engagement_id_id
            )

            from hr_external.models import HrExternalCategory

            new_category = eng.category_id
            if decision == RenewalDecision.CHANGE_CATEGORY and next_category_id:
                candidate = HrExternalCategory.objects.filter(
                    tenant_id=review.tenant_id, id=next_category_id, is_active=True
                ).first()
                if candidate is None:
                    raise RenewalStateConflict("EXTERNAL_CATEGORY_INVALID")
                new_category = candidate

            new_host_org = (
                next_host_org_id
                if decision == RenewalDecision.CHANGE_HOST_ORG and next_host_org_id
                else eng.host_organization_id
            )

            new_eng = HrExternalEngagement.objects.create(
                tenant_id=review.tenant_id,
                # 短序号防超长（多次续聘不拼接累积；unique 由 DB 约束兜底）
                engagement_no=f"E{(next_start or timezone.localdate()).year}{_uuid.uuid4().hex[:8].upper()}",
                person_id=eng.person_id,
                external_profile_id=eng.external_profile_id,
                category_id=new_category,
                purpose=eng.purpose,
                source_type=eng.source_type,
                source_case_id=eng.source_case_id,
                host_organization_id=new_host_org,
                start_at=next_start or eng.end_at or timezone.localdate(),
                end_at=next_end,
                review_at=next_end,
                workload_cap=eng.workload_cap,
                agreement_requirement=eng.agreement_requirement,
                agreement_status=eng.agreement_status,
                status=ExternalEngagementStatus.DRAFT,
            )
            review.next_engagement_id = new_eng
        elif decision == RenewalDecision.CONVERT_TO_REGULAR_HR_PROCESS:
            # 转正式员工：走 HR04/HR05/HR03 正式链（§62），不直接改 worker_kind
            eng = HrExternalEngagement.objects.select_for_update().get(
                tenant_id=tenant_id, id=review.engagement_id_id
            )
            eng.status = ExternalEngagementStatus.EXITING
            eng.version += 1
            eng.save(update_fields=["status", "version", "updated_at"])
        elif decision == RenewalDecision.DO_NOT_RENEW:
            eng = HrExternalEngagement.objects.select_for_update().get(
                tenant_id=tenant_id, id=review.engagement_id_id
            )
            eng.status = ExternalEngagementStatus.EXPIRED
            eng.version += 1
            eng.save(update_fields=["status", "version", "updated_at"])

        review.version += 1
        review.save(
            update_fields=[
                "decision",
                "status",
                "decided_by",
                "decided_at",
                "next_engagement_id",
                "version",
                "updated_at",
            ]
        )
        return decision
