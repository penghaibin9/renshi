"""
hr_onboarding/services/probation_service.py

试用与转正（HR05-05，总册 §17）：
- open_probation：Activation 后按政策创建（同 employment 一份进行中）；
- submit_review：员工自评 → 单位评价 → 人事审核（分角色）；
- confirm：CONFIRMED + outbox ProbationConfirmed（按 HR03 领域服务更新关系，不直接改多表）；
- extend：创建 HrProbationExtension 保留历史，不覆盖原日期；
- fail：ProbationFailed + 交 HR07/HR16 处理合同/离开；不 Employee.is_active=False；
- 终局（CONFIRMED/FAILED）后不可直接改。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    NotFoundError,
    ProbationAlreadyFinalizedError,
)
from hr_onboarding.constants import ProbationResult, ProbationStatus
from hr_onboarding.models import (
    HrOnboardingCase,
    HrProbationCase,
    HrProbationExtension,
    HrProbationReview,
)
from hr_onboarding.policies.state_machine import (
    assert_probation_transition,
    validate_probation_transition,
)
from hr_onboarding.services.outbox_service import enqueue_outbox

logger = logging.getLogger(__name__)


class ProbationService:
    def __init__(self, *, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 内部：probation 终局/推进联动 case 状态机（同事务）
    # ------------------------------------------------------------------
    def _sync_case(self, probation: HrProbationCase, to_status: str, action: str, reason: str):
        """probation 生命周期推进 case 状态（open→PROBATION；confirm→CONFIRMED；fail→PROBATION_FAILED；extend→PROBATION_EXTENDED）。"""
        if probation.onboarding_case is None:
            return
        from hr_onboarding.services.case_service import CaseService

        case = HrOnboardingCase.objects.select_for_update().get(id=probation.onboarding_case_id)
        from hr_onboarding.policies.state_machine import assert_case_transition

        assert_case_transition(case.status, to_status)
        CaseService(tenant_id=self.tenant_id, actor_user_id=self.actor_user_id)._transition_locked(
            case, to_status, action, reason
        )

    # ------------------------------------------------------------------
    # 开启试用
    # ------------------------------------------------------------------
    @transaction.atomic
    def open_probation(
        self,
        case: HrOnboardingCase,
        *,
        staff_master_id,
        employment_relationship_id,
        start_date: date,
        planned_end_date: date,
        policy_version_id: str = "",
    ) -> HrProbationCase:
        from hr_onboarding.constants import CaseStatus

        if planned_end_date <= start_date:
            raise Hr05ApiError("planned_end_date 必须晚于 start_date")
        # 前置：试用仅在 case 已正式生效后开启（总册 §17.1 / §66.3）
        if case.status not in (
            CaseStatus.ACTIVE,
            CaseStatus.ONBOARDING_IN_PROGRESS,
            CaseStatus.ONBOARDING_COMPLETED,
        ):
            raise Hr05ApiError(
                f"case 状态 {case.status} 不可开启试用（要求已 ACTIVE）",
                details={"code": "PROBATION_CASE_NOT_ACTIVE"},
            )
        # 同 employment 只允许一份进行中试用
        existing = HrProbationCase.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id=employment_relationship_id,
            status__in=(
                ProbationStatus.NOT_STARTED,
                ProbationStatus.IN_PROGRESS,
                ProbationStatus.REVIEW_DUE,
                ProbationStatus.UNDER_REVIEW,
                ProbationStatus.EXTENDED,
            ),
        ).first()
        if existing is not None:
            return existing
        probation = HrProbationCase.objects.create(
            tenant_id=self.tenant_id,
            onboarding_case=case,
            staff_master_id=staff_master_id,
            employment_relationship_id=employment_relationship_id,
            start_date=start_date,
            planned_end_date=planned_end_date,
            policy_version_id=policy_version_id,
            status=ProbationStatus.NOT_STARTED,
        )
        # 联动 case → PROBATION
        from hr_onboarding.constants import CaseStatus

        self._sync_case(probation, CaseStatus.PROBATION, "OPEN_PROBATION", "开启试用期")
        return probation

    @transaction.atomic
    def begin(self, probation: HrProbationCase) -> HrProbationCase:
        probation = HrProbationCase.objects.select_for_update().get(id=probation.id)
        assert_probation_transition(probation.status, ProbationStatus.IN_PROGRESS)
        probation.status = ProbationStatus.IN_PROGRESS
        probation.version += 1
        probation.save(update_fields=["status", "version", "updated_at"])
        return probation

    # ------------------------------------------------------------------
    # 评价
    # ------------------------------------------------------------------
    @transaction.atomic
    def submit_review(
        self,
        probation: HrProbationCase,
        *,
        review_type: str,
        content: str,
        decision: str = "",
    ) -> HrProbationReview:
        probation = HrProbationCase.objects.select_for_update().get(id=probation.id)
        if probation.status in (
            ProbationStatus.CONFIRMED,
            ProbationStatus.FAILED,
            ProbationStatus.CANCELLED,
        ):
            raise ProbationAlreadyFinalizedError("试用已终局，不可再提交评价")
        review = HrProbationReview.objects.create(
            tenant_id=self.tenant_id,
            probation_case=probation,
            review_type=review_type,
            reviewer_id=self.actor_user_id,
            content=content,
            decision=decision,
            submitted_at=timezone.now(),
        )
        # 评价期间状态推进（UNDER_REVIEW）：仅当迁移合法时推进，不静默吞错
        transition = validate_probation_transition(probation.status, ProbationStatus.UNDER_REVIEW)
        if transition.allowed:
            probation.status = ProbationStatus.UNDER_REVIEW
            probation.version += 1
            probation.save(update_fields=["status", "version", "updated_at"])
        return review

    # ------------------------------------------------------------------
    # 转正 / 延长 / 不通过
    # ------------------------------------------------------------------
    @transaction.atomic
    def confirm(
        self,
        probation: HrProbationCase,
        *,
        decision_reason: str = "",
        as_of: Optional[date] = None,
    ) -> HrProbationCase:
        probation = HrProbationCase.objects.select_for_update().get(id=probation.id)
        if probation.status in (
            ProbationStatus.CONFIRMED,
            ProbationStatus.FAILED,
            ProbationStatus.CANCELLED,
        ):
            raise ProbationAlreadyFinalizedError("试用已终局，不可转正")
        assert_probation_transition(probation.status, ProbationStatus.CONFIRMED)
        probation.status = ProbationStatus.CONFIRMED
        probation.result = ProbationResult.CONFIRMED
        # 学校时区由调用方（API 层 context.today()）注入；默认退化为服务器本地日期
        probation.actual_end_date = as_of or timezone.localdate()
        probation.version += 1
        probation.save(update_fields=["status", "result", "actual_end_date", "version", "updated_at"])
        # 联动 case → CONFIRMED
        from hr_onboarding.constants import CaseStatus

        self._sync_case(probation, CaseStatus.CONFIRMED, "PROBATION_CONFIRMED", "试用转正")
        enqueue_outbox(
            tenant_id=self.tenant_id,
            event_type="ProbationConfirmed",
            aggregate_type="HrProbationCase",
            aggregate_id=str(probation.id),
            payload={
                "probation_case_id": str(probation.id),
                "staff_master_id": str(probation.staff_master_id) if probation.staff_master_id else None,
                "employment_relationship_id": str(probation.employment_relationship_id)
                if probation.employment_relationship_id
                else None,
                "decision_reason": decision_reason,
            },
        )
        return probation

    @transaction.atomic
    def extend(
        self, probation: HrProbationCase, *, new_end_date: date, reason: str
    ) -> HrProbationCase:
        probation = HrProbationCase.objects.select_for_update().get(id=probation.id)
        if probation.status in (
            ProbationStatus.CONFIRMED,
            ProbationStatus.FAILED,
            ProbationStatus.CANCELLED,
        ):
            raise ProbationAlreadyFinalizedError("试用已终局，不可延长")
        if new_end_date <= probation.planned_end_date:
            raise Hr05ApiError("new_end_date 必须晚于当前 planned_end_date")
        # 保留历史（不覆盖旧日期）
        HrProbationExtension.objects.create(
            tenant_id=self.tenant_id,
            probation_case=probation,
            old_end_date=probation.planned_end_date,
            new_end_date=new_end_date,
            reason=reason,
            approval="APPROVED",
            created_by=self.actor_user_id,
        )
        probation.planned_end_date = new_end_date
        probation.extension_count += 1
        probation.status = ProbationStatus.EXTENDED
        probation.version += 1
        probation.save(
            update_fields=["planned_end_date", "extension_count", "status", "version", "updated_at"]
        )
        # 联动 case → PROBATION_EXTENDED
        from hr_onboarding.constants import CaseStatus

        self._sync_case(probation, CaseStatus.PROBATION_EXTENDED, "PROBATION_EXTENDED", "试用期延长")
        return probation

    @transaction.atomic
    def fail(self, probation: HrProbationCase, *, reason: str) -> HrProbationCase:
        probation = HrProbationCase.objects.select_for_update().get(id=probation.id)
        if probation.status == ProbationStatus.FAILED:
            raise ProbationAlreadyFinalizedError("试用已判不通过")
        assert_probation_transition(probation.status, ProbationStatus.FAILED)
        probation.status = ProbationStatus.FAILED
        probation.result = ProbationResult.FAILED
        probation.version += 1
        probation.save(update_fields=["status", "result", "version", "updated_at"])
        # 联动 case → PROBATION_FAILED（交 HR07/HR16 处理合同/离开）
        from hr_onboarding.constants import CaseStatus

        self._sync_case(probation, CaseStatus.PROBATION_FAILED, "PROBATION_FAILED", reason)
        # 交 HR07/HR16 处理合同/离开；HR05 不删除/禁用员工
        enqueue_outbox(
            tenant_id=self.tenant_id,
            event_type="ProbationFailed",
            aggregate_type="HrProbationCase",
            aggregate_id=str(probation.id),
            payload={
                "probation_case_id": str(probation.id),
                "staff_master_id": str(probation.staff_master_id) if probation.staff_master_id else None,
                "reason": reason,
            },
        )
        return probation

    # ------------------------------------------------------------------
    # 到期查询
    # ------------------------------------------------------------------
    def due_in_days(self, *, as_of: Optional[date] = None, within_days: int = 30):
        """planned_end_date 在 within_days 内到期的进行中试用（REVIEW_DUE 候选）。"""
        as_of = as_of or timezone.localdate()
        return HrProbationCase.objects.filter(
            tenant_id=self.tenant_id,
            status__in=(
                ProbationStatus.IN_PROGRESS,
                ProbationStatus.NOT_STARTED,
                ProbationStatus.UNDER_REVIEW,
            ),
            planned_end_date__lte=as_of + timedelta(days=within_days),
        )
