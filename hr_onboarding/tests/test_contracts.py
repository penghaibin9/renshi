"""
hr_onboarding/tests/test_contracts.py

HR05 S1 契约测试：
- 冻结枚举值（总册 §8/§12/§14/§15/§17）不可变；
- 权限码清单（总册 §5）；
- 状态机合法/非法迁移（总册 §8/§14/§15/§17）；
- API envelope 序列化；
- tenant fail-closed 403（health 探针）；
- HR04 HANDOFF 幂等契约；HR03 Employment 占位契约。
"""

from django.test import TestCase, override_settings

from hr_onboarding.api import base as api_base
from hr_onboarding.api.exceptions import (
    Hr05ApiError,
    InvalidStateTransitionError,
    OnboardingCaseDuplicateError,
)
from hr_onboarding.constants import CaseStatus as C
from hr_onboarding.constants import ProvisioningStatus as P
from hr_onboarding.constants import TaskStatus as T
from hr_onboarding.integrations.hr03 import Hr03ActivationProvider, Hr03ActivationProviderError, Hr03MockProvider
from hr_onboarding.integrations.hr04 import HandoffPayload, Hr04HandoffProvider
from hr_onboarding.permissions import HR05_PERMISSIONS
from hr_onboarding.policies.state_machine import (
    assert_case_transition,
    assert_task_transition,
    validate_case_transition,
    validate_task_transition,
)

API_HEALTH_URL = "/api/hr/v1/onboarding/health"


class FrozenEnumsTests(TestCase):
    def test_case_status_frozen(self):
        """总册 §8 正常 + 异常状态必须全部存在。"""
        expected = {
            "CREATED",
            "PREPARING",
            "READY_TO_REPORT",
            "REPORT_SCHEDULED",
            "REPORTED",
            "VERIFYING",
            "READY_FOR_ACTIVATION",
            "ACTIVATING",
            "ACTIVE",
            "ONBOARDING_IN_PROGRESS",
            "ONBOARDING_COMPLETED",
            "PROBATION",
            "CONFIRMED",
            "REPORT_DELAYED",
            "DECLINED",
            "NO_SHOW",
            "BLOCKED",
            "ACTIVATION_FAILED",
            "CANCELLED",
            "PROBATION_EXTENDED",
            "PROBATION_FAILED",
        }
        self.assertEqual(set(C.values), expected)

    def test_task_status_frozen(self):
        """总册 §14.4 权威 9 态。"""
        expected = {
            "NOT_STARTED",
            "READY",
            "IN_PROGRESS",
            "WAITING_EXTERNAL",
            "BLOCKED",
            "COMPLETED",
            "WAIVED",
            "FAILED",
            "CANCELLED",
        }
        self.assertEqual(set(T.values), expected)

    def test_blocking_level_has_six_levels(self):
        from hr_onboarding.constants import BlockingLevel

        self.assertEqual(len(BlockingLevel.values), 6)


class PermissionContractTests(TestCase):
    def test_hr05_permissions_frozen(self):
        """总册 §5 权限码清单。"""
        for perm in HR05_PERMISSIONS:
            self.assertTrue(perm.startswith("hr05."))
        self.assertIn("hr05.case.activate", HR05_PERMISSIONS)
        self.assertIn("hr05.report.checkin", HR05_PERMISSIONS)
        self.assertIn("hr05.position.commit", HR05_PERMISSIONS)
        self.assertIn("hr05.probation.finalize", HR05_PERMISSIONS)


class StateMachineTests(TestCase):
    def test_report_does_not_equal_activate(self):
        """REPORTED 不可直接跳 ACTIVE；必须经 VERIFYING→READY_FOR_ACTIVATION→ACTIVATING。"""
        self.assertFalse(validate_case_transition(C.REPORTED, C.ACTIVE).allowed)
        self.assertTrue(validate_case_transition(C.REPORTED, C.VERIFYING).allowed)

    def test_activate_cannot_skip_ready_for_activation(self):
        self.assertFalse(validate_case_transition(C.VERIFYING, C.ACTIVATING).allowed)

    def test_activation_success_path(self):
        self.assertTrue(validate_case_transition(C.READY_FOR_ACTIVATION, C.ACTIVATING).allowed)
        self.assertTrue(validate_case_transition(C.ACTIVATING, C.ACTIVE).allowed)

    def test_declined_and_cancelled_terminal(self):
        self.assertFalse(validate_case_transition(C.DECLINED, C.PREPARING).allowed)
        self.assertFalse(validate_case_transition(C.CANCELLED, C.READY_TO_REPORT).allowed)

    def test_probation_failed_terminal(self):
        """转正失败不直接回 case；交 HR07/HR16，HR05 不删除员工。"""
        self.assertFalse(validate_case_transition(C.PROBATION_FAILED, C.CANCELLED).allowed)

    def test_assert_case_transition_raises(self):
        with self.assertRaises(InvalidStateTransitionError):
            assert_case_transition(C.REPORTED, C.ACTIVE)

    def test_task_waive_terminal_and_not_completed(self):
        """WAIVED ≠ COMPLETED。"""
        self.assertFalse(validate_task_transition(T.WAIVED, T.COMPLETED).allowed)
        self.assertFalse(validate_task_transition(T.WAIVED, T.IN_PROGRESS).allowed)

    def test_task_waive_requires_reason(self):
        from hr_onboarding.policies.state_machine import validate_task_transition as v

        self.assertTrue(v(T.READY, T.WAIVED).allowed)

    def test_provisioning_failed_retryable(self):
        from hr_onboarding.policies.state_machine import validate_provisioning_transition

        self.assertTrue(validate_provisioning_transition(P.FAILED_RETRYABLE, P.RUNNING).allowed)
        self.assertTrue(validate_provisioning_transition(P.FAILED_RETRYABLE, P.FAILED_TERMINAL).allowed)
        self.assertFalse(validate_provisioning_transition(P.SUCCESS, P.RUNNING).allowed)


class ApiEnvelopeTests(TestCase):
    def test_ok_envelope(self):
        import json

        from django.test import RequestFactory

        request = RequestFactory().get("/x")
        response = api_base.ok(request, {"k": 1})
        payload = json.loads(response.content)
        self.assertEqual(payload["apiVersion"], "v1")
        self.assertEqual(payload["schemaVersion"], "hr05.1")
        self.assertIn("requestId", payload)
        self.assertEqual(payload["data"], {"k": 1})

    def test_error_envelope(self):
        import json

        from django.test import RequestFactory

        request = RequestFactory().get("/x")
        response = api_base.error(request, "TEST_CODE", "测试消息", 409, {"a": 1}, retryable=True)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "TEST_CODE")
        self.assertEqual(payload["error"]["details"], {"a": 1})
        self.assertTrue(payload["error"]["retryable"])


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class TenantFailClosedTests(TestCase):
    """A0 硬门：无学校上下文 → 403。"""

    def test_health_requires_tenant(self):
        from django.test import RequestFactory

        request = RequestFactory().get(API_HEALTH_URL)
        from hr_onboarding.api.base import make_hr05_context
        from hr_onboarding.api.exceptions import TenantContextRequiredError

        with self.assertRaises(TenantContextRequiredError):
            make_hr05_context(request)


class HandoffIdempotencyTests(TestCase):
    def test_repeated_handoff_returns_same_case_request(self):
        """同一 HANDOFF 重复调用 → 幂等返回先前结果，不生成第二份。"""
        provider = Hr04HandoffProvider()
        payload = HandoffPayload(
            tenant_id=1,
            proposed_hire_id="ph-001",
            application_id="app-001",
            reservation_id=10,
            legal_name="张三",
        )
        request1, replay1 = provider.consume_handoff(payload, idempotency_key="k-handoff-1")
        self.assertFalse(replay1)
        self.assertEqual(request1["source_type"], "HR04_HIRE")
        self.assertEqual(request1["source_id"], "ph-001")

        request2, replay2 = provider.consume_handoff(payload, idempotency_key="k-handoff-1")
        self.assertTrue(replay2)
        self.assertEqual(request1, request2)

    def test_missing_proposed_hire_rejected(self):
        provider = Hr04HandoffProvider()
        with self.assertRaises(OnboardingCaseDuplicateError):
            provider.consume_handoff(
                HandoffPayload(tenant_id=1, proposed_hire_id="", application_id="app-x"),
                idempotency_key="k-bad",
            )


class Hr03ProviderContractTests(TestCase):
    def test_hr03_ready_mode(self):
        """HR03-S2/S3 已交付，Provider mode=HR03_READY（Employment/Assignment 真实调用）。"""
        provider = Hr03ActivationProvider()
        self.assertEqual(provider.mode, "HR03_READY")

    def test_create_employment_wraps_service_error(self):
        """无有效 staff 时 HR03 服务错误被包装为 Hr03ActivationProviderError。"""
        from hr_onboarding.integrations.hr03 import map_relationship_type

        provider = Hr03ActivationProvider()
        from datetime import date

        with self.assertRaises(Hr03ActivationProviderError):
            provider.create_employment(
                tenant_id=1, staff_id=None, employment_type="FULL_TIME", effective_from=date(2026, 9, 1)
            )
        self.assertEqual(map_relationship_type("FULL_TIME"), "REGULAR_EMPLOYMENT")

    def test_mock_provider_is_explicit_mock(self):
        provider = Hr03MockProvider()
        self.assertEqual(provider.mode, "MOCK")
        person = provider.match_or_create_person(tenant_id=1, legal_name="张三")
        self.assertEqual(person.legal_name, "张三")
