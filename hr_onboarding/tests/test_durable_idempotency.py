from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
)
from hr_onboarding.models import (
    HrOnboardingCase,
    HrOnboardingIdempotencyRecord,
    IdempotencyStatus,
)
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.idempotency_service import (
    DurableIdempotencyService,
    canonical_request_hash,
)
from hr_onboarding.services.provisioning_service import ProvisioningService


def _handoff(tenant_id: int, source: str, *, legal_name: str = "张三"):
    return {
        "tenant_id": tenant_id,
        "source_type": "HR04_HIRE",
        "source_id": source,
        "hr04_proposed_hire_id": source,
        "hr04_application_id": f"app-{source}",
        "legal_name": legal_name,
        "employment_type": "FULL_TIME",
        "staff_category": "TEACHER",
    }


class DurableHandoffIdempotencyTests(TestCase):
    def tearDown(self):
        cache.clear()

    def test_cache_loss_or_process_restart_still_replays_authority(self):
        service = CaseService(tenant_id=1)
        first = service.create_case_from_handoff(
            _handoff(1, "restart-source"), idempotency_key="restart-key"
        )
        self.assertIn("portal_token", first)
        cache.clear()

        replay = CaseService(tenant_id=1).create_case_from_handoff(
            _handoff(1, "restart-source"), idempotency_key="restart-key"
        )

        self.assertEqual(replay["case_id"], first["case_id"])
        self.assertFalse(replay["created"])
        self.assertNotIn("portal_token", replay)
        self.assertEqual(HrOnboardingCase.objects.count(), 1)

    def test_same_key_different_payload_is_409_and_payload_is_not_persisted(self):
        service = CaseService(tenant_id=1)
        service.create_case_from_handoff(
            _handoff(1, "conflict-source", legal_name="敏感姓名甲"),
            idempotency_key="conflict-key",
        )
        with self.assertRaises(IdempotencyConflictError) as caught:
            service.create_case_from_handoff(
                _handoff(1, "conflict-source", legal_name="敏感姓名乙"),
                idempotency_key="conflict-key",
            )
        self.assertEqual(caught.exception.status_code, 409)
        record = HrOnboardingIdempotencyRecord.objects.get(
            tenant_id=1,
            operation="HANDOFF_CREATE_CASE",
            idempotency_key="conflict-key",
        )
        serialized = str(record.response_summary)
        self.assertNotIn("敏感姓名甲", serialized)
        self.assertNotIn("portal", serialized.lower())
        self.assertEqual(len(record.request_hash), 64)

    def test_same_raw_key_is_isolated_by_tenant_and_operation(self):
        one = CaseService(tenant_id=1).create_case_from_handoff(
            _handoff(1, "tenant-source"), idempotency_key="shared-key"
        )
        two = CaseService(tenant_id=2).create_case_from_handoff(
            _handoff(2, "tenant-source"), idempotency_key="shared-key"
        )
        case_one = HrOnboardingCase.objects.get(id=one["case_id"])
        provision = ProvisioningService(tenant_id=1).request_provisioning(
            case_one,
            target_system="IAM",
            operation="CREATE_SSO",
            payload={"account": "not-stored-in-receipt"},
            idempotency_key="shared-key",
        )
        self.assertNotEqual(one["case_id"], two["case_id"])
        self.assertIsNotNone(provision.id)
        self.assertEqual(
            HrOnboardingIdempotencyRecord.objects.filter(
                idempotency_key="shared-key"
            ).count(),
            3,
        )


class DurableClaimStateMachineTests(TestCase):
    def setUp(self):
        self.service = DurableIdempotencyService(
            tenant_id=9, operation="TEST_WRITE"
        )

    def test_live_lease_blocks_second_side_effect(self):
        first = self.service.claim(idempotency_key="lease-key", request_payload={"x": 1})
        self.assertTrue(first.execute)
        with self.assertRaises(IdempotencyInProgressError):
            self.service.claim(idempotency_key="lease-key", request_payload={"x": 1})
        self.assertEqual(
            HrOnboardingIdempotencyRecord.objects.filter(
                tenant_id=9, operation="TEST_WRITE", idempotency_key="lease-key"
            ).count(),
            1,
        )

    def test_request_hash_is_canonical(self):
        self.assertEqual(
            canonical_request_hash({"b": [2, 1], "a": {"x": True}}),
            canonical_request_hash({"a": {"x": True}, "b": [2, 1]}),
        )

    def test_retryable_failure_and_expired_crash_lease_can_be_reclaimed(self):
        first = self.service.claim(idempotency_key="retry-key", request_payload={"x": 1})
        self.service.fail(first.record, error_code="TEMPORARY", retryable=True)
        retry = self.service.claim(idempotency_key="retry-key", request_payload={"x": 1})
        self.assertTrue(retry.execute)
        self.assertEqual(retry.record.attempt_count, 2)

        retry.record.lease_expires_at = timezone.now() - timedelta(seconds=1)
        retry.record.save(update_fields=["lease_expires_at"])
        recovered = self.service.claim(idempotency_key="retry-key", request_payload={"x": 1})
        self.assertTrue(recovered.execute)
        self.assertEqual(recovered.record.attempt_count, 3)

    def test_terminal_failure_replays_without_execution(self):
        first = self.service.claim(idempotency_key="terminal-key", request_payload={"x": 1})
        self.service.fail(
            first.record,
            error_code="INVALID",
            retryable=False,
            response_summary={"ok": False, "error": "INVALID"},
        )
        replay = self.service.claim(idempotency_key="terminal-key", request_payload={"x": 1})
        self.assertFalse(replay.execute)
        self.assertEqual(replay.record.status, IdempotencyStatus.FAILED_TERMINAL)


class DurableProvisioningIdempotencyTests(TestCase):
    def _case(self, tenant_id: int, suffix: str):
        return HrOnboardingCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"PROV-{tenant_id}-{suffix}",
            source_type="HR04_HIRE",
            source_id=f"prov-source-{tenant_id}-{suffix}",
        )

    def test_same_request_replays_but_changed_payload_conflicts(self):
        case = self._case(1, "a")
        service = ProvisioningService(tenant_id=1)
        args = dict(
            target_system="IAM",
            operation="CREATE_SSO",
            payload={"username": "zhangsan"},
            idempotency_key="provision-key",
        )
        first = service.request_provisioning(case, **args)
        replay = service.request_provisioning(case, **args)
        self.assertEqual(first.id, replay.id)
        with self.assertRaises(IdempotencyConflictError):
            service.request_provisioning(
                case,
                target_system="IAM",
                operation="CREATE_SSO",
                payload={"username": "lisi"},
                idempotency_key="provision-key",
            )

    def test_same_raw_key_is_allowed_across_tenants(self):
        case1 = self._case(1, "shared")
        case2 = self._case(2, "shared")
        one = ProvisioningService(tenant_id=1).request_provisioning(
            case1,
            target_system="IAM",
            operation="CREATE_SSO",
            idempotency_key="cross-tenant-key",
        )
        two = ProvisioningService(tenant_id=2).request_provisioning(
            case2,
            target_system="IAM",
            operation="CREATE_SSO",
            idempotency_key="cross-tenant-key",
        )
        self.assertNotEqual(one.id, two.id)
