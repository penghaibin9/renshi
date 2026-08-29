"""
hr_external/services/exit_service.py —— 退出与权限回收（S8，总册 §63-70/§66/§105）。

- Exit Case 状态机：PLANNED→UNDER_REVIEW→READY_TO_EXIT→EXITING→ENDED→CLEARANCE_PENDING→CLOSED（§65）；
- 退出权限回收闭环（§66/§138.12）：Engagement ENDED 后触发 AccessService.revoke（§105 失败语义）；
- 历史任务/成果/评价/协议保留（§70/§138.15）：退出不删除历史；只停账号/权限/教务未来排课；
- 一个 Engagement 退出不误杀另一个（§138.14）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import transaction

from hr_external.constants import (
    ExitReason,
    ExitStatus,
    ExternalEngagementStatus,
)
from hr_external.models import HrExternalEngagement, HrExternalExitCase
from hr_external.services.access_service import AccessService


class ExitBlocked(Exception):
    code = "EXTERNAL_EXIT_BLOCKED"


class ExitStateConflict(Exception):
    code = "VERSION_CONFLICT"


class ExitService:
    def __init__(self, access: Optional[AccessService] = None):
        self.access = access or AccessService()

    @transaction.atomic
    def create_exit_case(
        self,
        *,
        tenant_id: int,
        engagement_id,
        exit_reason: str,
        planned_end_at: date,
        clearance_policy: str = "",
    ) -> HrExternalExitCase:
        eng = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id, id=engagement_id
        ).first()
        if eng is None:
            raise ExitBlocked("EXTERNAL_ENGAGEMENT_NOT_FOUND")
        # 只有已生效（active 系）聘期可进入退出；DRAFT/未批准/已结束不可
        if eng.status in (
            ExternalEngagementStatus.ENDED,
            ExternalEngagementStatus.ARCHIVED,
            ExternalEngagementStatus.DRAFT,
            ExternalEngagementStatus.UNDER_REVIEW,
            ExternalEngagementStatus.APPROVED,
            ExternalEngagementStatus.WAITING_AGREEMENT,
            ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
            ExternalEngagementStatus.REJECTED,
            ExternalEngagementStatus.CANCELLED,
            ExternalEngagementStatus.RETURNED,
        ):
            raise ExitBlocked(f"engagement status {eng.status} not exitable")

        case = HrExternalExitCase.objects.create(
            tenant_id=tenant_id,
            engagement_id=eng,
            exit_reason=exit_reason,
            planned_end_at=planned_end_at,
            required_clearance_policy=clearance_policy,
            status=ExitStatus.PLANNED,
        )
        # Engagement → EXITING（§20）
        eng.status = ExternalEngagementStatus.EXITING
        eng.save(update_fields=["status", "updated_at"])
        return case

    def start_exit(self, case: HrExternalExitCase):
        """READY_TO_EXIT → EXITING；记录实际结束日。"""
        if case.status != ExitStatus.READY_TO_EXIT:
            raise ExitStateConflict("case not ready to exit")
        case.status = ExitStatus.EXITING
        case.actual_end_at = case.actual_end_at or date.today()
        case.save(update_fields=["status", "actual_end_at", "updated_at"])

    def submit_review(self, case: HrExternalExitCase):
        """PLANNED → UNDER_REVIEW without ending the engagement."""
        if case.status != ExitStatus.PLANNED:
            raise ExitStateConflict("case not in planned state")
        case.status = ExitStatus.UNDER_REVIEW
        case.save(update_fields=["status", "updated_at"])

    def approve_exit(self, case: HrExternalExitCase):
        """UNDER_REVIEW → READY_TO_EXIT; finalization stays a separate action."""
        if case.status != ExitStatus.UNDER_REVIEW:
            raise ExitStateConflict("case not under review")
        case.status = ExitStatus.READY_TO_EXIT
        case.save(update_fields=["status", "updated_at"])

    @transaction.atomic
    def finalize_exit(
        self,
        case: HrExternalExitCase,
        *,
        tenant_id: int,
    ) -> HrExternalExitCase:
        """EXITING → ENDED：Engagement 置 ENDED，触发权限回收请求（§66/§105），历史保留（§70）。

        生产级并发防护：锁 exit case + engagement（避免并发 complete 重复回收/重复置 ENDED）。
        """
        case = HrExternalExitCase.objects.select_for_update().get(id=case.id)
        if case.status not in (ExitStatus.EXITING, ExitStatus.CLEARANCE_PENDING):
            raise ExitStateConflict("case not in exiting state")

        eng = HrExternalEngagement.objects.select_for_update().filter(
            tenant_id=tenant_id, id=case.engagement_id_id
        ).first()
        if eng is None:
            raise ExitBlocked("EXTERNAL_ENGAGEMENT_NOT_FOUND")
        if eng.status == ExternalEngagementStatus.ENDED:
            # 幂等：已结束则只收尾 case，不重复回收（00 §23）
            case.status = ExitStatus.ENDED
            case.actual_end_at = case.actual_end_at or date.today()
            case.save(update_fields=["status", "actual_end_at", "updated_at"])
            return case

        eng.status = ExternalEngagementStatus.ENDED
        eng.save(update_fields=["status", "updated_at"])

        # 权限回收闭环（§66）：发起 REVOKE 请求；失败 → Risk=CRITICAL（§105）
        self.access.revoke_engagement_access(tenant_id=tenant_id, engagement=eng)

        case.status = ExitStatus.ENDED
        case.actual_end_at = case.actual_end_at or date.today()
        case.save(update_fields=["status", "actual_end_at", "updated_at"])
        return case

    def close_exit(self, case: HrExternalExitCase, *, clearance_ok: bool = True):
        """ENDED → CLOSED（或 CLEARANCE_PENDING）。"""
        if clearance_ok:
            case.status = ExitStatus.CLOSED
        else:
            case.status = ExitStatus.CLEARANCE_PENDING
        case.save(update_fields=["status", "updated_at"])

    def record_clearance(self, case: HrExternalExitCase, items: list, ok: bool = True):
        """记录退出清单（§69）：任务验收/成绩提交/协议/结算/设备/账号/门禁/教务/归档。"""
        case.clearance_items = items
        case.status = ExitStatus.CLOSED if ok else ExitStatus.CLEARANCE_PENDING
        case.save(update_fields=["clearance_items", "status", "updated_at"])
