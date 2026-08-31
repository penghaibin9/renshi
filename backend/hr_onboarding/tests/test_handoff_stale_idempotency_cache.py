from django.core.cache import cache
from django.test import TestCase

from hr_onboarding.api.exceptions import IdempotencyConflictError
from hr_onboarding.models import HrOnboardingCase
from hr_onboarding.services.case_service import CaseService


class HandoffStaleIdempotencyCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_missing_authority_case_never_returns_or_recreates_false_success(self):
        service = CaseService(tenant_id=1)
        request = {
            "tenant_id": 1,
            "source_type": "HR04_HIRE",
            "source_id": "stale-cache-source",
            "hr04_proposed_hire_id": "stale-cache-source",
            "hr04_application_id": "stale-cache-application",
            "legal_name": "缓存恢复测试",
            "employment_type": "FULL_TIME",
            "staff_category": "TEACHER",
        }

        first = service.create_case_from_handoff(
            request,
            idempotency_key="stale-cache-key",
        )
        first_case_id = first["case_id"]
        self.assertTrue(first["created"])

        # Simulate database reset/restore while the 24h cache entry survives.
        HrOnboardingCase.objects.filter(tenant_id=1, id=first_case_id).delete()
        self.assertFalse(
            HrOnboardingCase.objects.filter(tenant_id=1, id=first_case_id).exists()
        )

        with self.assertRaises(IdempotencyConflictError):
            service.create_case_from_handoff(
                request,
                idempotency_key="stale-cache-key",
            )
        self.assertEqual(HrOnboardingCase.objects.count(), 0)
