"""
hr_onboarding/tests/test_s6.py

HR05-S4/S6 协同任务 + Provisioning 测试：
- 模板→实例化幂等；前置任务 DAG 校验；
- task start/complete/waive（waive 需 reason）；
- provisioning 幂等、SUCCESS 必须 external_ref、FAILED_RETRYABLE→重试→FAILED_TERMINAL。
"""

from unittest import mock

from django.test import TestCase

from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    TaskAlreadyCompletedError,
    TaskPrerequisiteNotMetError,
)
from hr_onboarding.constants import ProvisioningStatus, TaskStatus
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingTaskDefinition,
    HrOnboardingTaskInstance,
    HrProvisioningRequest,
)
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.provisioning_service import ProvisioningService
from hr_onboarding.services.task_service import TaskService

from .test_s3 import _handoff_request
from .test_models_s2 import _build_template


def _prepared_case(tenant_id=1):
    import uuid as _uuid

    _, version, _ = _build_template(tenant_id=tenant_id)
    service = CaseService(tenant_id=tenant_id)
    r = service.create_case_from_handoff(
        _handoff_request(idem_key=f"k-s6-handoff-{_uuid.uuid4().hex}"),
        idempotency_key=f"k-s6-case-{_uuid.uuid4().hex}",
    )
    case = HrOnboardingCase.objects.get(id=r["case_id"])
    case.template_version_id = version.id
    case.save(update_fields=["template_version_id"])
    return case, version


class TaskServiceTests(TestCase):
    def setUp(self):
        self.case, self.version = _prepared_case()
        self.service = TaskService(tenant_id=1, actor_user_id=9)

    def test_instantiate_idempotent(self):
        n1 = self.service.instantiate_tasks(self.case)
        n2 = self.service.instantiate_tasks(self.case)
        self.assertEqual(n1, 1)  # _build_template 建了 1 个 task def
        self.assertEqual(n2, 0)
        inst = HrOnboardingTaskInstance.objects.get(case=self.case)
        self.assertEqual(inst.status, TaskStatus.NOT_STARTED)
        self.assertEqual(inst.assignee_type, "IT_SERVICE")

    def test_task_lifecycle(self):
        self.service.instantiate_tasks(self.case)
        inst = HrOnboardingTaskInstance.objects.get(case=self.case)
        started = self.service.start_task(inst)
        self.assertEqual(started.status, TaskStatus.IN_PROGRESS)
        completed = self.service.complete_task(started, note="邮箱已开通", evidence={"ref": "mail-1"})
        self.assertEqual(completed.status, TaskStatus.COMPLETED)
        self.assertEqual(completed.completion_payload["completed_by"], 9)
        self.assertIn("mail-1", completed.completion_payload["evidence"]["ref"])
        # 已完成不可再完成
        with self.assertRaises(TaskAlreadyCompletedError):
            self.service.complete_task(completed, note="again")

    def test_prerequisite_blocked(self):
        """前置任务未完成 → TASK_PREREQUISITE_NOT_MET。"""
        case2, version = _prepared_case(tenant_id=2)
        self.service2 = TaskService(tenant_id=2, actor_user_id=9)
        # 修改定义：让它依赖一个不存在的 code
        HrOnboardingTaskDefinition.objects.filter(template_version=version).update(
            prerequisite_codes=["NOT-EXIST"]
        )
        self.service2.instantiate_tasks(case2)
        inst = HrOnboardingTaskInstance.objects.get(case=case2)
        with self.assertRaises(TaskPrerequisiteNotMetError):
            self.service2.complete_task(inst, note="x")

    def test_waive_requires_reason(self):
        self.service.instantiate_tasks(self.case)
        inst = HrOnboardingTaskInstance.objects.get(case=self.case)
        with self.assertRaises(Hr05ApiError):
            self.service.waive_task(inst, reason="")
        waived = self.service.waive_task(inst, reason="学校政策豁免")
        self.assertEqual(waived.status, TaskStatus.WAIVED)
        self.assertEqual(waived.completion_payload["reason"], "学校政策豁免")


class ProvisioningServiceTests(TestCase):
    def setUp(self):
        self.case, _ = _prepared_case()
        self.service = ProvisioningService(tenant_id=1)

    def test_request_idempotent(self):
        r1 = self.service.request_provisioning(
            self.case,
            target_system="IAM",
            operation="CREATE_SSO",
            idempotency_key="prov-1",
            payload={"username": "zhangsan"},
        )
        r2 = self.service.request_provisioning(
            self.case,
            target_system="IAM",
            operation="CREATE_SSO",
            idempotency_key="prov-1",
        )
        self.assertEqual(r1.id, r2.id)
        self.assertEqual(r1.status, ProvisioningStatus.PENDING)
        self.assertEqual(r1.payload_json, {"username": "zhangsan"})

    def test_success_requires_external_ref(self):
        req = self.service.request_provisioning(
            self.case, target_system="IAM", operation="CREATE_SSO", idempotency_key="prov-2"
        )
        self.service.mark_running(req)
        with self.assertRaises(ValueError):
            self.service.mark_success(req)
        done = self.service.mark_success(req, external_ref="sso-abc")
        self.assertEqual(done.status, ProvisioningStatus.SUCCESS)
        self.assertEqual(done.external_ref, "sso-abc")

    def test_failed_retryable_then_terminal(self):
        req = self.service.request_provisioning(
            self.case, target_system="IAM", operation="CREATE_SSO", idempotency_key="prov-3"
        )
        self.service.mark_running(req)
        failed = self.service.mark_failed(req, error="timeout", retryable=True)
        self.assertEqual(failed.status, ProvisioningStatus.FAILED_RETRYABLE)
        self.assertIsNotNone(failed.next_retry_at)
        self.assertEqual(failed.attempt_count, 1)

        # 重试：每次 mark_running 后 mark_failed；attempt 达到 MAX 后进入 FAILED_TERMINAL
        for _ in range(ProvisioningService.MAX_ATTEMPTS + 2):
            try:
                self.service.mark_running(req)
                self.service.mark_failed(req, error="timeout", retryable=True)
            except Exception:
                break  # FAILED_TERMINAL 后 mark_running 非法 → 终止
        req.refresh_from_db()
        self.assertEqual(req.status, ProvisioningStatus.FAILED_TERMINAL)

    def test_reconcile_mismatch_marks_failed(self):
        req = self.service.request_provisioning(
            self.case, target_system="IAM", operation="CREATE_SSO", idempotency_key="prov-4"
        )
        self.service.mark_running(req)
        ok = self.service.reconcile(req, external_ok=False)
        self.assertFalse(ok)
        req.refresh_from_db()
        self.assertEqual(req.status, ProvisioningStatus.FAILED_RETRYABLE)
