"""
hr10_development/tests/test_s2_plan.py

S2 发展计划测试。
"""
from datetime import date

from django.test import TestCase

from hr10_development.constants import PlanLifecycleStatus, PlanVersionStatus, PlanType
from hr10_development.models.plan import HrDevelopmentPlan
from hr10_development.services.plan_service import PlanService


class PlanLifecycleTest(TestCase):
    """发展计划状态机测试。"""

    TENANT_ID = 10001

    def setUp(self):
        self.plan = HrDevelopmentPlan.objects.create(
            tenant_id=self.TENANT_ID,
            plan_no="PLAN-2026-001",
            plan_type=PlanType.SCHOOL,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

    def test_initial_state_is_draft(self):
        self.assertEqual(self.plan.lifecycle_status, PlanLifecycleStatus.DRAFT)

    def test_draft_to_preparing(self):
        ok = self.plan.transition_to(PlanLifecycleStatus.PREPARING)
        self.assertTrue(ok)
        self.assertEqual(self.plan.lifecycle_status, PlanLifecycleStatus.PREPARING)

    def test_draft_to_ready_for_review(self):
        ok = self.plan.transition_to(PlanLifecycleStatus.READY_FOR_REVIEW)
        self.assertTrue(ok)

    def test_draft_to_published_blocked(self):
        """DRAFT 不能直接跳到 PUBLISHED。"""
        ok = self.plan.transition_to(PlanLifecycleStatus.PUBLISHED)
        self.assertFalse(ok)

    def test_rejected_is_terminal(self):
        """REJECTED 是终态，不能再转。"""
        self.plan.lifecycle_status = PlanLifecycleStatus.REJECTED
        ok = self.plan.transition_to(PlanLifecycleStatus.DRAFT)
        self.assertFalse(ok)

    def test_cancelled_is_terminal(self):
        self.plan.lifecycle_status = PlanLifecycleStatus.CANCELLED
        ok = self.plan.transition_to(PlanLifecycleStatus.DRAFT)
        self.assertFalse(ok)

    def test_full_happy_path(self):
        """DRAFT → READY_FOR_REVIEW → (手动设 UNDER_REVIEW) → APPROVED → PUBLISHED → ACTIVE → CLOSING → CLOSED → ARCHIVED"""
        path = [
            PlanLifecycleStatus.READY_FOR_REVIEW,
            PlanLifecycleStatus.UNDER_REVIEW,
            PlanLifecycleStatus.APPROVED,
            PlanLifecycleStatus.PUBLISHED,
            PlanLifecycleStatus.ACTIVE,
            PlanLifecycleStatus.CLOSING,
            PlanLifecycleStatus.CLOSED,
            PlanLifecycleStatus.ARCHIVED,
        ]
        for i, target in enumerate(path):
            ok = self.plan.transition_to(target)
            self.assertTrue(ok, f"Step {i}: {target} failed from {self.plan.lifecycle_status}")
            self.plan.save()

    def test_create_version_and_freeze(self):
        """创建版本并冻结。"""
        version = PlanService.create_version(
            plan=self.plan,
            objectives_json={"goal": "提升教师数字化能力"},
            population_snapshot={"total": 500},
            budget_snapshot={"total": 100000},
            policy_snapshot={"rule": "V2026"},
            target_snapshot={"hours": 60},
            effective_from=date(2026, 1, 1),
        )
        self.assertEqual(version.version_no, 1)
        self.assertEqual(version.status, PlanVersionStatus.DRAFT)
        self.assertNotEqual(version.content_hash, "")

        # 冻结版本
        ok = PlanService.freeze_version(version)
        self.assertTrue(ok)
        version.refresh_from_db()
        self.assertEqual(version.status, PlanVersionStatus.FROZEN)

    def test_version_number_increment(self):
        """版本号自增。"""
        v1 = PlanService.create_version(
            plan=self.plan,
            objectives_json={"v": 1},
            population_snapshot={}, budget_snapshot={}, policy_snapshot={},
            target_snapshot={},
        )
        v2 = PlanService.create_version(
            plan=self.plan,
            objectives_json={"v": 2},
            population_snapshot={}, budget_snapshot={}, policy_snapshot={},
            target_snapshot={},
        )
        self.assertEqual(v1.version_no, 1)
        self.assertEqual(v2.version_no, 2)

    def test_unique_plan_no_per_tenant(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            HrDevelopmentPlan.objects.create(
                tenant_id=self.TENANT_ID,
                plan_no="PLAN-2026-001",  # duplicate
                plan_type=PlanType.COLLEGE,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
            )
