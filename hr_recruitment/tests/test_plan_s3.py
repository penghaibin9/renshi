"""
hr_recruitment/tests/test_plan_s3.py

HR04-01 年度用人计划（S3）测试：
- PlanService 状态机：DRAFT→SUBMITTED→UNDER_HR_REVIEW→RETURNED→RESUBMITTED→UNDER_SCHOOL_APPROVAL→APPROVED；
- RETURNED ≠ REJECTED：RETURNED 可改重提，REJECTED 不可重提；
- 批准并发重检：额度不足 → PARTIALLY_APPROVED；额度不可用 → 拒绝批准（fail-closed）；
- 需求行额度非负约束。
"""

from datetime import date

from django.test import TestCase

from hr_recruitment.api.exceptions import (
    InvalidStateTransitionError,
    PositionCapacityConflictError,
)
from hr_recruitment.constants import PlanRequestStatus
from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanLine, HrHiringPlanRequest
from hr_recruitment.policies.capacity import PositionCapacitySnapshot
from hr_recruitment.services.plan_service import PlanService

TENANT = 2001


class FakeCapacityProvider:
    """测试用容量 Provider：模拟 HR02 可用额度。"""

    def __init__(self, available: int, status: str = "OK"):
        self._available = available
        self._status = status

    def query_capacity(self, *, tenant_id, organization_id, **kwargs):
        return PositionCapacitySnapshot(
            position_id=None,
            position_pool_id=None,
            post_catalog_id=None,
            authorized_count=self._available,
            reserved_count=0,
            available_count=self._available,
            status=self._status,
        )


class PlanServiceTests(TestCase):
    def setUp(self):
        self.cycle = HrHiringPlanCycle.objects.create(
            tenant_id=TENANT,
            year=2026,
            title="2026 用人计划",
            start_date=date(2026, 1, 1),
        )
        self.service = PlanService()

    def _make_request(self, lines=None):
        req = HrHiringPlanRequest.objects.create(
            tenant_id=TENANT,
            cycle_id=self.cycle,
            organization_name="计算机学院",
        )
        for line in lines or [{"requested_headcount": 2}]:
            HrHiringPlanLine.objects.create(
                tenant_id=TENANT,
                request_id=req,
                post_catalog_name="专任教师",
                requested_headcount=line["requested_headcount"],
            )
        return req

    def test_full_approval_flow(self):
        req = self._make_request()
        self.assertEqual(req.status, PlanRequestStatus.DRAFT)

        self.service.submit(str(req.id), tenant_id=TENANT)
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.SUBMITTED)

        self.service.start_hr_review(str(req.id), tenant_id=TENANT)
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.UNDER_HR_REVIEW)

        self.service.return_to_college(str(req.id), tenant_id=TENANT, reason="材料不齐")
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.RETURNED)

        self.service.submit(str(req.id), tenant_id=TENANT)
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.RESUBMITTED)

        self.service.start_hr_review(str(req.id), tenant_id=TENANT)
        self.service.submit_to_school(str(req.id), tenant_id=TENANT)
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.UNDER_SCHOOL_APPROVAL)

        self.service.approve(str(req.id), tenant_id=TENANT, capacity_provider=FakeCapacityProvider(5))
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.APPROVED)
        self.assertEqual(req.total_approved, 2)

    def test_partial_approval_when_capacity_insufficient(self):
        req = self._make_request(lines=[{"requested_headcount": 3}])
        self.service.submit(str(req.id), tenant_id=TENANT)
        self.service.start_hr_review(str(req.id), tenant_id=TENANT)
        self.service.submit_to_school(str(req.id), tenant_id=TENANT)
        self.service.approve(str(req.id), tenant_id=TENANT, capacity_provider=FakeCapacityProvider(1))
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.PARTIALLY_APPROVED)
        self.assertEqual(req.total_approved, 1)
        line = req.lines.first()
        self.assertEqual(line.approved_headcount, 1)

    def test_approve_fails_closed_when_capacity_unavailable(self):
        """额度 UNAVAILABLE 时禁止批准（fail-closed，不放行超批）。"""
        req = self._make_request()
        self.service.submit(str(req.id), tenant_id=TENANT)
        self.service.start_hr_review(str(req.id), tenant_id=TENANT)
        self.service.submit_to_school(str(req.id), tenant_id=TENANT)
        with self.assertRaises(PositionCapacityConflictError):
            self.service.approve(
                str(req.id), tenant_id=TENANT, capacity_provider=FakeCapacityProvider(0, status="UNAVAILABLE")
            )
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.UNDER_SCHOOL_APPROVAL)

    def test_rejected_cannot_resubmit(self):
        """REJECTED 是终态，不可直接重提。"""
        req = self._make_request()
        self.service.submit(str(req.id), tenant_id=TENANT)
        self.service.start_hr_review(str(req.id), tenant_id=TENANT)
        self.service.submit_to_school(str(req.id), tenant_id=TENANT)
        self.service.reject(str(req.id), tenant_id=TENANT, reason="校核不通过")
        req.refresh_from_db()
        self.assertEqual(req.status, PlanRequestStatus.REJECTED)
        with self.assertRaises(InvalidStateTransitionError):
            self.service.submit(str(req.id), tenant_id=TENANT)

    def test_illegal_transition_raises(self):
        req = self._make_request()
        # DRAFT → APPROVED 非法
        with self.assertRaises(InvalidStateTransitionError):
            self.service.approve(str(req.id), tenant_id=TENANT)

    def test_empty_request_cannot_submit(self):
        req = HrHiringPlanRequest.objects.create(
            tenant_id=TENANT, cycle_id=self.cycle, organization_name="空学院"
        )
        from hr_recruitment.services.plan_service import PlanServiceError

        with self.assertRaises(PlanServiceError):
            self.service.submit(str(req.id), tenant_id=TENANT)
