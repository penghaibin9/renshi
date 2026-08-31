"""
hr_recruitment/tests/test_contracts.py

HR04 S1 契约测试：
- 冻结枚举值（总册 8.4/9.4/9.5/13.6/14.1）不可变；
- 权限码清单（总册 6.3）；
- 状态机合法/非法迁移（总册 11.4/14）；
- API envelope 序列化；
- tenant fail-closed 403（health 探针）；
- HR02 容量 Provider 未接线时 UNAVAILABLE 降级。
"""

from django.test import TestCase, override_settings

from hr_recruitment.api import base as api_base
from hr_recruitment.api.exceptions import (
    InvalidStateTransitionError,
    PositionCapacityConflictError,
)
from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.permissions import HR04_PERMISSIONS
from hr_recruitment.policies.capacity import CapacityProvider
from hr_recruitment.policies.state_machine import (
    assert_transition,
    validate_reopen_transition,
    validate_transition,
)

API_HEALTH_URL = "/api/hr/v1/recruitment/health"


class FrozenEnumsTests(TestCase):
    def test_application_canonical_status_frozen(self):
        """总册 14.1 冻结 24 态必须全部存在。"""
        expected = {
            "DRAFT",
            "SUBMITTED",
            "UNDER_REVIEW",
            "RETURNED",
            "RESUBMITTED",
            "QUALIFIED",
            "DISQUALIFIED",
            "ASSESSMENT_PENDING",
            "ASSESSING",
            "ASSESSMENT_PASSED",
            "ASSESSMENT_FAILED",
            "MEDICAL_PENDING",
            "MEDICAL_REVIEW",
            "BACKGROUND_PENDING",
            "BACKGROUND_REVIEW",
            "PROPOSED_HIRE",
            "PUBLIC_NOTICE",
            "OFFER_PENDING",
            "OFFERED",
            "OFFER_ACCEPTED",
            "OFFER_DECLINED",
            "HANDOFF_TO_HR05",
            "WITHDRAWN",
            "CANCELLED",
        }
        self.assertEqual(set(S.values), expected)

    def test_offer_status_frozen(self):
        expected = {
            "DRAFT",
            "APPROVED",
            "ISSUED",
            "VIEWED",
            "ACCEPTED",
            "DECLINED",
            "EXPIRED",
            "WITHDRAWN",
        }
        from hr_recruitment.constants import OfferStatus

        self.assertEqual(set(OfferStatus.values), expected)


class PermissionContractTests(TestCase):
    def test_hr04_permissions_frozen(self):
        """总册 6.3 权限码清单。"""
        for perm in HR04_PERMISSIONS:
            self.assertTrue(perm.startswith("hr04."))


class StateMachineTests(TestCase):
    def test_returned_cannot_go_hired(self):
        """总册 11.4 禁止 RETURNED → HIRED（常规）。"""
        result = validate_transition(S.RETURNED, S.HANDOFF_TO_HR05)
        self.assertFalse(result.allowed)

    def test_disqualified_cannot_go_assessing(self):
        result = validate_transition(S.DISQUALIFIED, S.ASSESSING)
        self.assertFalse(result.allowed)

    def test_returned_can_resubmit(self):
        result = validate_transition(S.RETURNED, S.RESUBMITTED)
        self.assertTrue(result.allowed)

    def test_under_review_can_return_and_qualify(self):
        self.assertTrue(validate_transition(S.UNDER_REVIEW, S.RETURNED).allowed)
        self.assertTrue(validate_transition(S.UNDER_REVIEW, S.QUALIFIED).allowed)
        self.assertTrue(validate_transition(S.UNDER_REVIEW, S.DISQUALIFIED).allowed)

    def test_submitted_can_withdraw(self):
        self.assertTrue(validate_transition(S.SUBMITTED, S.WITHDRAWN).allowed)

    def test_assert_transition_raises(self):
        with self.assertRaises(InvalidStateTransitionError):
            assert_transition(S.RETURNED, S.HANDOFF_TO_HR05)

    def test_reopen_transition_requires_privilege_flow(self):
        """DISQUALIFIED 只能经特权 REOPEN 回到审核。"""
        self.assertTrue(validate_reopen_transition(S.DISQUALIFIED, S.UNDER_REVIEW).allowed)
        self.assertFalse(validate_transition(S.DISQUALIFIED, S.UNDER_REVIEW).allowed)


class ApiEnvelopeTests(TestCase):
    def test_ok_envelope(self):
        import json

        from django.test import RequestFactory

        request = RequestFactory().get("/x")
        response = api_base.ok(request, {"k": 1})
        payload = json.loads(response.content)
        self.assertEqual(payload["apiVersion"], "v1")
        self.assertEqual(payload["schemaVersion"], "hr04.1")
        self.assertIn("requestId", payload)
        self.assertEqual(payload["data"], {"k": 1})

    def test_error_envelope(self):
        import json

        from django.test import RequestFactory

        request = RequestFactory().get("/x")
        response = api_base.error(request, "TEST_CODE", "测试消息", 409, {"a": 1})
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "TEST_CODE")
        self.assertEqual(payload["error"]["details"], {"a": 1})


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class TenantFailClosedTests(TestCase):
    """A0 硬门：无学校上下文 → 403。"""

    def test_health_requires_tenant(self):
        from django.test import RequestFactory

        request = RequestFactory().get(API_HEALTH_URL)
        # 未登录且无 selected_company → resolve_tenant_from_request 返回 None
        from hr_recruitment.api.base import make_hr04_context
        from hr_recruitment.api.exceptions import TenantContextRequiredError

        with self.assertRaises(TenantContextRequiredError):
            make_hr04_context(request)


class CapacityProviderTests(TestCase):
    def test_unavailable_when_no_reference(self):
        """HR02 未就绪：无岗位引用 → UNAVAILABLE，禁止臆造额度。"""
        provider = CapacityProvider()
        snapshot = provider.query_capacity(
            tenant_id=1, organization_id=1, post_catalog_id=10
        )
        self.assertEqual(snapshot.status, "UNAVAILABLE")
        with self.assertRaises(PositionCapacityConflictError):
            from hr_recruitment.policies.capacity import require_capacity_for_reservation

            require_capacity_for_reservation(snapshot, 1)
