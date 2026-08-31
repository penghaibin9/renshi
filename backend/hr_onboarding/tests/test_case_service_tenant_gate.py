from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_onboarding.api.exceptions import OnboardingCaseInvalidSourceError
from hr_onboarding.models import HrOnboardingIdempotencyRecord
from hr_onboarding.services.case_service import CaseService


class CaseServiceTenantGateTests(TestCase):
    def test_handoff_idempotency_is_namespaced_by_tenant(self):
        CaseService(tenant_id=77).create_case_from_handoff(
            {"source_type": "HR04_HIRE", "source_id": "hire-1", "tenant_id": 77},
            "same-key",
        )

        self.assertTrue(
            HrOnboardingIdempotencyRecord.objects.filter(
                tenant_id=77,
                operation="HANDOFF_CREATE_CASE",
                idempotency_key="same-key",
            ).exists()
        )

    @patch("hr_onboarding.services.case_service.HrOnboardingCase.objects")
    def test_case_lock_is_explicitly_tenant_scoped(self, case_objects):
        locked = MagicMock()
        locked.get.return_value = SimpleNamespace(id=9, tenant_id=77)
        case_objects.select_for_update.return_value = locked

        case = CaseService(tenant_id=77)._case_for_update(9)

        locked.get.assert_called_once_with(id=9, tenant_id=77)
        self.assertEqual(case.tenant_id, 77)

    def test_handoff_rejects_cross_tenant_payload_before_create(self):
        with self.assertRaisesRegex(OnboardingCaseInvalidSourceError, "tenant mismatch"):
            CaseService(tenant_id=77).create_case_from_handoff(
                {"source_type": "HR04_HIRE", "source_id": "hire-1", "tenant_id": 88},
                "key",
            )

    def test_service_requires_tenant(self):
        with self.assertRaises(OnboardingCaseInvalidSourceError):
            CaseService(tenant_id=0)
