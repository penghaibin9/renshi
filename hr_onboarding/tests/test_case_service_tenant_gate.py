from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.test import SimpleTestCase

from hr_onboarding.api.exceptions import OnboardingCaseInvalidSourceError
from hr_onboarding.services.case_service import CaseService


class CaseServiceTenantGateTests(SimpleTestCase):
    @patch("hr_onboarding.services.case_service.apply_idempotency", return_value=None)
    @patch("hr_onboarding.services.case_service.HrOnboardingCase.objects")
    def test_handoff_idempotency_is_namespaced_by_tenant(self, case_objects, apply_idempotency):
        case_objects.filter.return_value.exists.return_value = True

        with self.assertRaises(Exception):
            CaseService(tenant_id=77).create_case_from_handoff(
                {"source_type": "HR04_HIRE", "source_id": "hire-1", "tenant_id": 77},
                "same-key",
            )

        apply_idempotency.assert_called_once_with("hr05:handoff:tenant:77:same-key")

    @patch("hr_onboarding.services.case_service.HrOnboardingCase.objects")
    def test_case_lock_is_explicitly_tenant_scoped(self, case_objects):
        locked = MagicMock()
        locked.get.return_value = SimpleNamespace(id=9, tenant_id=77)
        case_objects.select_for_update.return_value = locked

        case = CaseService(tenant_id=77)._case_for_update(9)

        locked.get.assert_called_once_with(id=9, tenant_id=77)
        self.assertEqual(case.tenant_id, 77)

    @patch("hr_onboarding.services.case_service.apply_idempotency", return_value=None)
    def test_handoff_rejects_cross_tenant_payload_before_create(self, apply_idempotency):
        with self.assertRaisesRegex(OnboardingCaseInvalidSourceError, "tenant mismatch"):
            CaseService(tenant_id=77).create_case_from_handoff(
                {"source_type": "HR04_HIRE", "source_id": "hire-1", "tenant_id": 88},
                "key",
            )

    def test_service_requires_tenant(self):
        with self.assertRaises(OnboardingCaseInvalidSourceError):
            CaseService(tenant_id=0)
