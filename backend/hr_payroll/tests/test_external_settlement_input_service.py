import uuid

from django.test import TestCase

from hr_payroll.models import ExternalSettlementBasisInput
from hr_payroll.services.external_settlement_service import (
    ExternalSettlementInputError,
    ExternalSettlementInputService,
)


class ExternalSettlementInputServiceTests(TestCase):
    tenant_id = 77

    def setUp(self):
        self.engagement_id = uuid.uuid4()
        self.service = ExternalSettlementInputService(self.tenant_id)

    def _receive(self, **overrides):
        payload = {
            "engagement_id": self.engagement_id,
            "period": "2026-09",
            "source_version": 1,
            "verified_workload": "60.00",
            "eligible_items": [{"taskId": "TASK-1", "quantity": 60}],
            "policy_ref": "EXT-LECTURE-2026",
            "idempotency_key": "hr08-basis-1-v1",
        }
        payload.update(overrides)
        return self.service.receive(**payload)

    def test_receive_is_idempotent_and_tenant_scoped(self):
        first = self._receive()
        replay = self._receive()
        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.value.id, replay.value.id)
        self.assertEqual(
            ExternalSettlementBasisInput.objects.filter(tenant_id=self.tenant_id).count(),
            1,
        )

    def test_reused_key_with_different_payload_is_conflict(self):
        self._receive()
        with self.assertRaises(ExternalSettlementInputError) as caught:
            self._receive(verified_workload="61.00")
        self.assertEqual(caught.exception.code, "EXTERNAL_SETTLEMENT_IDEMPOTENCY_CONFLICT")

    def test_revised_basis_appends_source_version(self):
        first = self._receive()
        second = self._receive(
            source_version=2,
            verified_workload="65.00",
            idempotency_key="hr08-basis-1-v2",
        )
        self.assertNotEqual(first.value.id, second.value.id)
        self.assertEqual(
            ExternalSettlementBasisInput.objects.filter(
                tenant_id=self.tenant_id,
                source_engagement_id=self.engagement_id,
                period_code="2026-09",
            ).count(),
            2,
        )

    def test_received_input_cannot_be_modified_or_deleted(self):
        value = self._receive().value
        value.verified_workload = 99
        with self.assertRaisesRegex(ValueError, "PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE"):
            value.save()
        with self.assertRaisesRegex(ValueError, "PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE"):
            value.delete()
        with self.assertRaisesRegex(ValueError, "PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE"):
            ExternalSettlementBasisInput.objects.filter(id=value.id).update(
                verified_workload=100
            )
        with self.assertRaisesRegex(ValueError, "PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE"):
            ExternalSettlementBasisInput.objects.filter(id=value.id).delete()
