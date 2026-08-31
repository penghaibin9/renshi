"""
hr_onboarding/tests/test_concurrency.py

HR05-S10 并发/幂等测试（总册 §47）：
- 双 Activate 同一 case：第二个要么幂等返回原结果，要么被状态/锁拒绝，不重复创建；
- task 双完成 → TaskAlreadyCompletedError；
- 转正双审批 → ProbationAlreadyFinalizedError；
- 同一 HR04 来源并发建 case → source unique 兜底拒绝；
- case_no 并发唯一由 DB 约束兜底（不同 tenant 可同号）。
"""

from datetime import date, timedelta
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_onboarding.api.exceptions import (
    OnboardingCaseDuplicateError,
    ProbationAlreadyFinalizedError,
    TaskAlreadyCompletedError,
)
from hr_onboarding.constants import CaseStatus
from hr_onboarding.integrations.hr03 import Hr03MockProvider
from hr_onboarding.models import (
    HrActivationAttempt,
    HrOnboardingCase,
    HrOnboardingTaskInstance,
    HrProbationCase,
)
from hr_onboarding.services.activation_service import ActivationService
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.probation_service import ProbationService
from hr_onboarding.services.task_service import TaskService

from .test_s3 import _handoff_request
from .test_s4 import _ready_case, _FakeHr02
from .test_s6 import _prepared_case


class DualActivateTests(TestCase):
    def test_second_activate_returns_same_result(self):
        """同一 idempotency_key 双 Activate → 幂等返回原结果，不重复创建。"""
        case = _ready_case(CaseService(tenant_id=1))
        from datetime import date

        service = ActivationService(
            tenant_id=1,
            actor_user_id=1,
            hr03_provider=Hr03MockProvider(),
            hr02_provider_factory=lambda: _FakeHr02(),
        )
        r1 = service.activate(case, effective_at=date(2026, 9, 1), idempotency_key="k-conc-1")
        r2 = service.activate(case, effective_at=date(2026, 9, 1), idempotency_key="k-conc-1")
        self.assertEqual(r1["case_id"], r2["case_id"])
        self.assertEqual(r1["staff_master_id"], r2["staff_master_id"])
        # mock HR03 的 StaffMasterService 保证唯一
        self.assertEqual(
            HrActivationAttempt.objects.filter(case=case, status="SUCCEEDED").count(), 1
        )

    def test_duplicate_handoff_source_rejected(self):
        service = CaseService(tenant_id=1)
        req = _handoff_request(idem_key="k-conc-handoff-1")
        service.create_case_from_handoff(req, idempotency_key="k-conc-case-1")
        # 同一 source 不同幂等键 → DB unique 兜底
        with self.assertRaises(OnboardingCaseDuplicateError):
            service.create_case_from_handoff(req, idempotency_key="k-conc-case-1b")

    def test_case_no_tenant_scoped_unique(self):
        """同 case_no 不同 tenant 允许；同 tenant 拒绝（DB 兜底）。"""
        service = CaseService(tenant_id=1)
        r1 = service.create_case_from_handoff(
            _handoff_request(idem_key="k-conc-handoff-2"), idempotency_key="k-conc-case-2"
        )
        case1 = HrOnboardingCase.objects.get(id=r1["case_id"])
        # 直接改 case_no 模拟冲突
        case1.case_no = "DUPE-1"
        case1.save(update_fields=["case_no"])
        # 同 tenant 同 case_no 建另一条（不同 source）→ IntegrityError
        case2 = HrOnboardingCase(
            tenant_id=1,
            case_no="DUPE-1",
            source_type="HR04_HIRE",
            source_id="ph-dupe",
            status=CaseStatus.CREATED,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            case2.save()


class TaskDualCompleteTests(TestCase):
    def test_double_complete_rejected(self):
        case, _ = _prepared_case()
        service = TaskService(tenant_id=1, actor_user_id=9)
        service.instantiate_tasks(case)
        inst = HrOnboardingTaskInstance.objects.get(case=case)
        service.start_task(inst)
        service.complete_task(inst, note="done")
        with self.assertRaises(TaskAlreadyCompletedError):
            service.complete_task(inst, note="again")


class ProbationDualFinalizeTests(TestCase):
    def setUp(self):
        from uuid import uuid4

        self.case = _prepared_case()[0]
        # open_probation is deliberately fail-closed unless onboarding is
        # already ACTIVE. This concurrency fixture bypasses HR03 but must still
        # establish the same authoritative precondition.
        self.case.status = CaseStatus.ACTIVE
        self.case.save(update_fields=["status"])
        self.service = ProbationService(tenant_id=1, actor_user_id=9)
        today = date(2026, 9, 1)
        self.probation = self.service.open_probation(
            self.case,
            staff_master_id=uuid4(),
            employment_relationship_id=uuid4(),
            start_date=today,
            planned_end_date=today + timedelta(days=180),
        )
        self.service.begin(self.probation)

    def test_double_confirm_rejected(self):
        self.service.confirm(self.probation)
        with self.assertRaises(ProbationAlreadyFinalizedError):
            self.service.confirm(self.probation)

    def test_double_fail_rejected(self):
        self.service.fail(self.probation, reason="不合格")
        with self.assertRaises(ProbationAlreadyFinalizedError):
            self.service.fail(self.probation, reason="again")
