"""
hr_recruitment/services/proposed_hire_service.py

HR04-06 拟录用服务（《04_HR04_总册》§13）。

创建时必须锁定并验证（§13.3）：
- Application 当前合法；
- 资格 QUALIFIED（或已过资格阶段）；
- 必要 Selection 完成（评分表 LOCKED）；
- 必要体检/考察符合；
- HR02 reservation 有效；
- 录用人数不超过岗位上限。

决策：PROPOSE → APPROVE（审批人）/ REJECT / WITHDRAW。
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from hr_recruitment.api.exceptions import PositionCapacityConflictError
from hr_recruitment.constants import (
    ApplicationCanonicalStatus as S,
    ProposedHireDecision,
    ScoreSheetStatus,
)
from hr_recruitment.models import (
    HrCandidateScoreSheet,
    HrJobApplication,
    HrProposedHire,
    HrRecruitmentPosition,
)


class ProposedHireServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class ProposedHireService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    @transaction.atomic
    def create(
        self,
        *,
        application_id: str,
        rank: int,
        reservation_id: str = "",
        reservation_no: str = "",
        decision_reason: str = "",
    ) -> HrProposedHire:
        """创建拟录用（校验资格/选拔/体检/额度）。"""
        app = HrJobApplication.objects.select_related("recruitment_position_id").get(
            id=application_id, tenant_id=self.tenant_id
        )
        position = app.recruitment_position_id

        # 1) 申请状态合法（QUALIFIED 或已进入选拔/体检）
        if app.canonical_status not in (
            S.QUALIFIED,
            S.ASSESSMENT_PASSED,
            S.MEDICAL_REVIEW,
            S.BACKGROUND_REVIEW,
        ):
            raise ProposedHireServiceError(
                "APPLICATION_NOT_ELIGIBLE",
                f"当前状态 {app.canonical_status} 不可拟录用",
                http_status=409,
            )

        # 2) 必要选拔完成（至少一个 LOCKED 评分表，若有评分方案版本）
        has_scheme = app.selection_scheme_version_id is not None
        if has_scheme:
            locked = HrCandidateScoreSheet.objects.filter(
                tenant_id=self.tenant_id,
                application_id=app,
                status=ScoreSheetStatus.LOCKED,
            ).exists()
            if not locked:
                raise ProposedHireServiceError(
                    "ASSESSMENT_NOT_LOCKED", "存在评分方案但无锁定评分结果，禁止拟录用", http_status=409
                )

        # 3) 额度校验：已拟录用人数 < max_hires
        already = HrProposedHire.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=position,
            approval_status__in=[ProposedHireDecision.PROPOSE, ProposedHireDecision.APPROVE],
        ).count()
        if already >= position.max_hires:
            raise PositionCapacityConflictError(
                f"招聘岗位已满额（{already}/{position.max_hires}），禁止再拟录用"
            )

        # 4) rank 唯一
        if HrProposedHire.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=position,
            rank=rank,
        ).exists():
            raise ProposedHireServiceError("RANK_TAKEN", f"排名 {rank} 已被占用", http_status=409)

        # 综合成绩 = 锁定评分表总分聚合
        final_score = Decimal(0)
        for sheet in HrCandidateScoreSheet.objects.filter(
            tenant_id=self.tenant_id,
            application_id=app,
            status=ScoreSheetStatus.LOCKED,
        ):
            final_score += sheet.total_score

        proposed = HrProposedHire.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            recruitment_position_id=position,
            rank=rank,
            final_score=final_score,
            reservation_id=reservation_id,
            reservation_no=reservation_no,
            decision=ProposedHireDecision.PROPOSE,
            decision_reason=decision_reason,
            approval_status=ProposedHireDecision.PROPOSE,
            created_by=self.actor,
        )

        # 申请状态 → PROPOSED_HIRE
        app.canonical_status = S.PROPOSED_HIRE
        app.version += 1
        app.save(update_fields=["canonical_status", "version"])
        return proposed

    @transaction.atomic
    def decide(
        self,
        *,
        proposed_hire_id: str,
        decision: str,
        reason: str = "",
        approving_user: str = "",
    ) -> HrProposedHire:
        """决策：PROPOSE → APPROVE（特权）/ REJECT / WITHDRAW。"""
        proposed = self._get(proposed_hire_id)
        if proposed.approval_status in (ProposedHireDecision.APPROVE,):
            raise ProposedHireServiceError("ALREADY_APPROVED", "拟录用已批准", http_status=409)

        proposed.decision = decision
        proposed.approval_status = decision
        proposed.decision_reason = reason or proposed.decision_reason
        if decision == ProposedHireDecision.APPROVE:
            proposed.approved_by = approving_user or self.actor
            proposed.approved_at = timezone.now()
        proposed.version += 1
        proposed.save(
            update_fields=[
                "decision",
                "approval_status",
                "decision_reason",
                "approved_by",
                "approved_at",
                "version",
            ]
        )
        return proposed

    def _get(self, proposed_hire_id: str) -> HrProposedHire:
        try:
            return HrProposedHire.objects.get(
                id=proposed_hire_id, tenant_id=self.tenant_id
            )
        except HrProposedHire.DoesNotExist:
            raise ProposedHireServiceError("PROPOSED_HIRE_NOT_FOUND", "拟录用不存在", http_status=404)
