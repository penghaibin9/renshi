"""
hr_recruitment/services/plan_service.py

HR04-01 年度用人计划服务（《04_HR04_总册》§8）。

状态机（§8.4）：
  DRAFT → SUBMITTED → UNDER_HR_REVIEW → RETURNED(退回可重提)
  → RESUBMITTED → UNDER_SCHOOL_APPROVAL → APPROVED / PARTIALLY_APPROVED
  REJECTED / CLOSED 为终态（REJECTED 不可直接重提）。

硬规则：
- RETURNED ≠ REJECTED；RETURNED 可改重提，REJECTED 不可。
- 批准时事务重查 HR02 可用额度（§8.6 并发）：禁止按页面快照直接批准。
- 需求额度 non-negative（DB Check 兜底）。
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from hr_recruitment.api.exceptions import (
    InvalidStateTransitionError,
    PositionCapacityConflictError,
)
from hr_recruitment.constants import PlanLineStatus, PlanRequestStatus
from hr_recruitment.models import HrHiringPlanLine, HrHiringPlanRequest


class PlanServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class PlanService:
    """年度用人计划领域服务。"""

    # ---- 请求级状态机 ----

    _ALLOWED = {
        PlanRequestStatus.DRAFT: {PlanRequestStatus.SUBMITTED, PlanRequestStatus.CLOSED},
        PlanRequestStatus.SUBMITTED: {PlanRequestStatus.UNDER_HR_REVIEW, PlanRequestStatus.RETURNED},
        PlanRequestStatus.UNDER_HR_REVIEW: {
            PlanRequestStatus.RETURNED,
            PlanRequestStatus.UNDER_SCHOOL_APPROVAL,
        },
        PlanRequestStatus.RETURNED: {PlanRequestStatus.RESUBMITTED, PlanRequestStatus.CLOSED},
        PlanRequestStatus.RESUBMITTED: {PlanRequestStatus.UNDER_HR_REVIEW, PlanRequestStatus.RETURNED},
        PlanRequestStatus.UNDER_SCHOOL_APPROVAL: {
            PlanRequestStatus.APPROVED,
            PlanRequestStatus.PARTIALLY_APPROVED,
            PlanRequestStatus.REJECTED,
            PlanRequestStatus.RETURNED,
        },
        PlanRequestStatus.APPROVED: {PlanRequestStatus.CLOSED},
        PlanRequestStatus.PARTIALLY_APPROVED: {
            PlanRequestStatus.CLOSED,
            PlanRequestStatus.UNDER_SCHOOL_APPROVAL,  # 补批剩余额度
        },
        PlanRequestStatus.REJECTED: set(),
        PlanRequestStatus.CLOSED: set(),
    }

    def _assert(self, current: str, target: str) -> None:
        allowed = self._ALLOWED.get(current, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"非法计划状态迁移: {current} -> {target}"
            )

    # ---- 周期级操作 ----

    def create_cycle(self, *, tenant_id, year, title, start_date, actor=""):
        from django.db import IntegrityError as DbIntegrityError

        from hr_recruitment.models import HrHiringPlanCycle

        if HrHiringPlanCycle.objects.filter(tenant_id=tenant_id, year=year).exists():
            raise PlanServiceError(
                "PLAN_CYCLE_DUPLICATE", f"{year} 年度用人计划周期已存在", http_status=409
            )
        try:
            return HrHiringPlanCycle.objects.create(
                tenant_id=tenant_id,
                year=year,
                title=title,
                start_date=start_date,
                created_by=actor,
            )
        except DbIntegrityError:
            raise PlanServiceError(
                "PLAN_CYCLE_DUPLICATE", f"{year} 年度用人计划周期已存在", http_status=409
            )

    # ---- 请求级操作 ----

    @transaction.atomic
    def submit(self, request_id: str, *, tenant_id: int, actor: str = ""):
        """提交/重提。DRAFT→SUBMITTED；RETURNED→RESUBMITTED。"""
        req = self._get(request_id, tenant_id)
        target = (
            PlanRequestStatus.RESUBMITTED
            if req.status == PlanRequestStatus.RETURNED
            else PlanRequestStatus.SUBMITTED
        )
        self._assert(req.status, target)
        if not req.lines.exists():
            raise PlanServiceError(
                "PLAN_REQUEST_EMPTY", "需求申请至少包含一行需求", http_status=422
            )
        req.status = target
        req.submitted_at = timezone.now()
        req.version += 1
        req.save(update_fields=["status", "submitted_at", "version"])
        return req

    @transaction.atomic
    def start_hr_review(self, request_id: str, *, tenant_id: int, actor: str = ""):
        req = self._get(request_id, tenant_id)
        self._assert(req.status, PlanRequestStatus.UNDER_HR_REVIEW)
        req.status = PlanRequestStatus.UNDER_HR_REVIEW
        req.version += 1
        req.save(update_fields=["status", "version"])
        return req

    @transaction.atomic
    def return_to_college(
        self, request_id: str, *, tenant_id: int, reason: str, actor: str = ""
    ):
        """退回（RETURNED，可修改后重提）。"""
        req = self._get(request_id, tenant_id)
        self._assert(req.status, PlanRequestStatus.RETURNED)
        req.status = PlanRequestStatus.RETURNED
        req.returned_reason = reason
        req.version += 1
        req.save(update_fields=["status", "returned_reason", "version"])
        return req

    @transaction.atomic
    def submit_to_school(self, request_id: str, *, tenant_id: int, actor: str = ""):
        req = self._get(request_id, tenant_id)
        self._assert(req.status, PlanRequestStatus.UNDER_SCHOOL_APPROVAL)
        req.status = PlanRequestStatus.UNDER_SCHOOL_APPROVAL
        req.version += 1
        req.save(update_fields=["status", "version"])
        return req

    @transaction.atomic
    def approve(self, request_id: str, *, tenant_id: int, actor: str = "", capacity_provider=None):
        """
        批准（PARTIALLY_APPROVED 或 APPROVED）。

        并发重检（§8.6）：在事务内对每个 line 重新查询 HR02 可用额度，
        禁止按页面打开时的快照直接批准。额度不足的行自动降为 PARTIALLY_APPROVED。
        """
        req = self._get(request_id, tenant_id)
        self._assert(req.status, PlanRequestStatus.APPROVED)
        if req.status in (
            PlanRequestStatus.UNDER_SCHOOL_APPROVAL,
            PlanRequestStatus.PARTIALLY_APPROVED,
        ):
            # 事务重检 + 行锁防并发（UNDER_SCHOOL_APPROVAL 首次批；PARTIALLY_APPROVED 补批剩余）
            lines = list(
                HrHiringPlanLine.objects.select_for_update().filter(
                    request_id=req, tenant_id=tenant_id
                )
            )
            full_approved = True
            approved_count = 0
            for line in lines:
                # 已批额度保留，只对未批准部分补批
                remaining = max(line.requested_headcount - line.approved_headcount, 0)
                if remaining <= 0:
                    approved_count += line.approved_headcount
                    continue
                available = self._available_headcount(
                    line, tenant_id=tenant_id, capacity_provider=capacity_provider
                )
                approve_qty = min(remaining, available)
                if approve_qty < remaining:
                    full_approved = False
                line.approved_headcount += approve_qty
                line.status = (
                    PlanLineStatus.APPROVED
                    if line.approved_headcount == line.requested_headcount
                    and line.approved_headcount > 0
                    else PlanLineStatus.PARTIALLY_APPROVED
                )
                line.save(update_fields=["approved_headcount", "status"])
                approved_count += line.approved_headcount

            req.total_approved = approved_count
            req.status = (
                PlanRequestStatus.APPROVED
                if full_approved
                else PlanRequestStatus.PARTIALLY_APPROVED
            )
            req.approved_at = timezone.now()
            req.version += 1
            req.save(
                update_fields=["total_approved", "status", "approved_at", "version"]
            )
        return req

    @transaction.atomic
    def reject(self, request_id: str, *, tenant_id: int, reason: str, actor: str = ""):
        req = self._get(request_id, tenant_id)
        self._assert(req.status, PlanRequestStatus.REJECTED)
        req.status = PlanRequestStatus.REJECTED
        req.returned_reason = reason
        req.version += 1
        req.save(update_fields=["status", "returned_reason", "version"])
        return req

    def _available_headcount(self, line, *, tenant_id, capacity_provider=None):
        """单行额度：优先 HR02 容量 Provider；STALE/UNAVAILABLE/ERROR 一律 fail-closed。"""
        provider = capacity_provider
        if provider is None:
            from hr_recruitment.policies.capacity import CapacityProvider

            provider = CapacityProvider()
        try:
            snapshot = provider.query_capacity(
                tenant_id=tenant_id,
                organization_id=line.request_id.organization_id or 0,
                post_catalog_id=line.post_catalog_id,
                position_id=line.position_id,
                position_pool_id=line.position_pool_id,
            )
        except Exception as exc:  # noqa: BLE001
            # HR02 未接线/查询失败 → fail-closed，禁止批准
            raise PositionCapacityConflictError(
                f"计划批准需要 HR02 岗位额度校验，当前额度不可用（{getattr(exc, 'code', 'HR02_CAPACITY_ERROR')}），禁止批准"
            ) from exc
        if snapshot.status in ("UNAVAILABLE", "ERROR", "STALE"):
            # 额度不可用/过期：fail-closed，不放行超批（STALE 与 UNAVAILABLE 同权）
            raise PositionCapacityConflictError(
                "计划批准需要 HR02 岗位额度校验，当前额度不可用或已过期，禁止批准"
            )
        if snapshot.available_count is None:
            raise PositionCapacityConflictError(
                "计划批准需要 HR02 岗位额度校验，可用额度未知，禁止臆造额度"
            )
        return min(snapshot.available_count, line.requested_headcount)

    def _get(self, request_id: str, tenant_id: int) -> HrHiringPlanRequest:
        try:
            return HrHiringPlanRequest.objects.select_related("cycle_id").get(
                id=request_id, tenant_id=tenant_id
            )
        except HrHiringPlanRequest.DoesNotExist:
            raise PlanServiceError("PLAN_REQUEST_NOT_FOUND", "需求申请不存在", http_status=404)
