"""
hr_onboarding/services/case_service.py

Onboarding Case 编排（HR05-01 待报到人员）：
- create_case_from_handoff：HR04 HANDOFF 幂等建 case（source unique 兜底）+ 签发 Portal；
- confirm_intent / request_delay / approve_delay / decline：意愿与延期（延期不覆盖原日期，保留历史）；
- transition：状态迁移（含 HrOnboardingStageTransition ledger）；
- decline 时释放 Position Reservation（HR02 Provider）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    OnboardingCaseDuplicateError,
    OnboardingCaseInvalidSourceError,
    PositionReservationInvalidError,
)
from hr_onboarding.constants import (
    CaseSourceType,
    CaseStatus,
    PersonMatchStatus,
    ReportDelayApprovalStatus,
)
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingStageTransition,
    HrPrehireProfile,
    HrReportDelay,
)
from hr_onboarding.policies.idempotency import apply_idempotency, normalize_key, store_result
from hr_onboarding.policies.state_machine import assert_case_transition
from hr_onboarding.services.token_service import issue_portal_access

logger = logging.getLogger(__name__)


def _next_case_no(tenant_id: int) -> str:
    """case_no 生成：OB-{tenant}-{yyyymmdd}-{uuid 前 6}（无并发竞争，tenant 唯一约束兜底）。"""
    return f"OB-{tenant_id}-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


class CaseService:
    def __init__(self, *, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # HR04 HANDOFF → 建 case（幂等，RecruitToHireMapping §1.3）
    # 入参为 Hr04HandoffProvider.consume_handoff 返回的 case_create_request dict，
    # 幂等存储保存同一 dict，保证重复调用返回原结果。
    # ------------------------------------------------------------------
    @transaction.atomic
    def create_case_from_handoff(
        self,
        request: dict,
        idempotency_key: str,
        *,
        portal_ttl_days: int = 30,
    ) -> dict:
        key = normalize_key(idempotency_key, namespace="hr05:handoff")
        replay = apply_idempotency(key)
        if replay is not None:
            return replay

        source_type = request.get("source_type")
        source_id = request.get("source_id")
        if not source_type or not source_id:
            raise OnboardingCaseInvalidSourceError("handoff 缺少来源标识")
        if source_type not in CaseSourceType.values:
            raise OnboardingCaseInvalidSourceError(f"非法来源类型: {source_type}")

        # DB unique(tenant,source_type,source_id) 兜底并发
        if HrOnboardingCase.objects.filter(
            tenant_id=self.tenant_id,
            source_type=source_type,
            source_id=source_id,
        ).exists():
            raise OnboardingCaseDuplicateError("同一 HR04 录用来源已存在 onboarding case")

        case = HrOnboardingCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=_next_case_no(self.tenant_id),
            source_type=source_type,
            source_id=source_id,
            hr04_proposed_hire_id=request.get("hr04_proposed_hire_id") or None,
            hr04_application_id=request.get("hr04_application_id") or None,
            candidate_id=request.get("candidate_id"),
            position_reservation_id_id=request.get("position_reservation_id"),
            planned_organization_id_id=request.get("planned_organization_id"),
            planned_post_catalog_id_id=request.get("planned_post_catalog_id"),
            planned_position_id_id=request.get("planned_position_id"),
            employment_type=request.get("employment_type", "FULL_TIME"),
            staff_category=request.get("staff_category", "TEACHER"),
            expected_report_date=request.get("expected_report_date"),
            status=CaseStatus.CREATED,
        )
        HrOnboardingStageTransition.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            from_stage="",
            to_stage=CaseStatus.CREATED,
            action="HANDOFF_CREATED",
            actor_user_id=self.actor_user_id,
            reason="HR04 HANDOFF 创建 case",
        )
        HrPrehireProfile.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            legal_name=request.get("legal_name", ""),
            preferred_name=request.get("preferred_name", ""),
        )
        _, plaintext_token = issue_portal_access(
            tenant_id=self.tenant_id, case=case, ttl_days=portal_ttl_days
        )

        result = {
            "case_id": str(case.id),
            "case_no": case.case_no,
            "status": case.status,
            "portal_token": plaintext_token,  # 仅首次创建时返回一次；调用方负责不落日志
            "created": True,
        }
        # 幂等 cache 不存明文 token（避免 cache/Redis 泄漏）：重放返回无 token 副本
        replay_result = {k: v for k, v in result.items() if k != "portal_token"}
        replay_result["created"] = False
        store_result(key, replay_result)
        return result

    # ------------------------------------------------------------------
    # 意愿 / 延期 / 放弃
    # ------------------------------------------------------------------
    def confirm_intent(self, case: HrOnboardingCase) -> HrOnboardingCase:
        with transaction.atomic():
            case = HrOnboardingCase.objects.select_for_update().get(id=case.id)
            assert_case_transition(case.status, CaseStatus.PREPARING)
            self._transition_locked(case, CaseStatus.PREPARING, "CONFIRM_INTENT", "候选人确认入职意愿")
            # expected_report_date 由 HR04 来源或延期审批提供；不在此自动填"今天"（学校时区纪律）
            case.save(update_fields=["updated_at"])
        return case

    def request_delay(
        self, case: HrOnboardingCase, *, new_date: date, reason: str
    ) -> HrReportDelay:
        """
        申请延期：只记录 HrReportDelay（保留历史），不直接覆盖 expected_report_date。
        审批通过后再改日期（approve_delay）。
        """
        with transaction.atomic():
            case = HrOnboardingCase.objects.select_for_update().get(id=case.id)
            if not case.expected_report_date:
                raise PositionReservationInvalidError("尚无预计报到日期，不能申请延期")
            delay = HrReportDelay.objects.create(
                tenant_id=self.tenant_id,
                case=case,
                old_date=case.expected_report_date,
                new_date=new_date,
                reason=reason,
                approval_status=ReportDelayApprovalStatus.PENDING,
                requested_by=self.actor_user_id,
            )
            # case 进入 REPORT_DELAYED 等待审批（不覆盖日期）
            # 状态机仅允许 PREPARING/READY_TO_REPORT/REPORT_SCHEDULED → REPORT_DELAYED
            if case.status in (
                CaseStatus.PREPARING,
                CaseStatus.READY_TO_REPORT,
                CaseStatus.REPORT_SCHEDULED,
            ):
                assert_case_transition(case.status, CaseStatus.REPORT_DELAYED)
                self._transition_locked(case, CaseStatus.REPORT_DELAYED, "REQUEST_DELAY", reason)
        return delay

    def approve_delay(self, case: HrOnboardingCase, delay: HrReportDelay) -> HrOnboardingCase:
        """审批延期：更新 expected_report_date（历史保留在 HrReportDelay），case 回到可预约。"""
        with transaction.atomic():
            case = HrOnboardingCase.objects.select_for_update().get(id=case.id)
            delay = HrReportDelay.objects.select_for_update().get(id=delay.id)
            if delay.approval_status != ReportDelayApprovalStatus.PENDING:
                return case
            delay.approval_status = ReportDelayApprovalStatus.APPROVED
            delay.decided_by = self.actor_user_id
            delay.decided_at = timezone.now()
            delay.save(update_fields=["approval_status", "decided_by", "decided_at"])
            case.expected_report_date = delay.new_date
            assert_case_transition(case.status, CaseStatus.READY_TO_REPORT)
            self._transition_locked(case, CaseStatus.READY_TO_REPORT, "APPROVE_DELAY", "延期审批通过")
            case.save(update_fields=["expected_report_date", "updated_at"])
        return case

    def decline(self, case: HrOnboardingCase, *, reason: str = "") -> HrOnboardingCase:
        """
        放弃入职：case → DECLINED；必须释放 Position Reservation（HR02 Provider）。
        释放失败不得静默跳过（显式抛错，可补偿）。
        """
        from hr_onboarding.integrations.hr02 import Hr02PositionProvider

        with transaction.atomic():
            case = HrOnboardingCase.objects.select_for_update().get(id=case.id)
            if case.status == CaseStatus.DECLINED:
                return case  # 幂等
            assert_case_transition(case.status, CaseStatus.DECLINED)
            if case.position_reservation_id_id:
                provider = Hr02PositionProvider(self.tenant_id)
                provider.release(case.position_reservation_id_id)
            self._transition_locked(case, CaseStatus.DECLINED, "DECLINE", reason)
        return case

    # ------------------------------------------------------------------
    # Person 匹配（Activation 前）
    # ------------------------------------------------------------------
    def resolve_person_match(
        self, case: HrOnboardingCase, *, person_id, status: str = PersonMatchStatus.EXACT_MATCH
    ) -> HrOnboardingCase:
        with transaction.atomic():
            case = HrOnboardingCase.objects.select_for_update().get(id=case.id)
            case.hr03_person_id = person_id
            case.person_match_status = status
            case.save(update_fields=["hr03_person_id", "person_match_status", "updated_at"])
        return case

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _transition_locked(self, case: HrOnboardingCase, to_status: str, action: str, reason: str):
        from_status = case.status
        case.status = to_status
        case.current_stage_code = to_status
        case.version += 1
        case.save(update_fields=["status", "current_stage_code", "version", "updated_at"])
        HrOnboardingStageTransition.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            from_stage=from_status,
            to_stage=to_status,
            action=action,
            actor_user_id=self.actor_user_id,
            reason=reason,
        )
