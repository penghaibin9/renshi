from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_onboarding.models import HrActivationAttempt, HrOnboardingCase


class ActivationAttemptTenantIdempotencyTests(TestCase):
    def _case(self, tenant_id: int, suffix: str):
        return HrOnboardingCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"IDEM-{tenant_id}-{suffix}",
            source_type="HR04_HIRE",
            source_id=f"source-{tenant_id}-{suffix}",
        )

    def test_same_raw_key_is_allowed_across_tenants_but_unique_inside_tenant(self):
        case_t1 = self._case(1, "a")
        case_t2 = self._case(2, "a")

        first = HrActivationAttempt.objects.create(
            tenant_id=1,
            case=case_t1,
            idempotency_key="shared-client-key",
        )
        second = HrActivationAttempt.objects.create(
            tenant_id=2,
            case=case_t2,
            idempotency_key="shared-client-key",
        )
        self.assertNotEqual(first.id, second.id)

        duplicate_case = self._case(1, "b")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrActivationAttempt.objects.create(
                    tenant_id=1,
                    case=duplicate_case,
                    idempotency_key="shared-client-key",
                )
