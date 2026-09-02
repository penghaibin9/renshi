import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_external.integrations.base import ProviderStatus
from hr_external.integrations.hr15 import SettlementProvider
from hr_payroll.services.external_settlement_service import ExternalSettlementInputError


class ExternalSettlementProviderContractTests(SimpleTestCase):
    def _payload(self):
        return {
            "tenant_id": 77,
            "engagement_id": str(uuid.uuid4()),
            "period": "2026-09",
            "verified_workload": {"total": "60.00"},
            "eligible_items": [{"taskId": "TASK-1", "quantity": 60}],
            "policy_ref": "EXT-LECTURE-2026",
            "source_version": 2,
            "idempotency_key": "hr08-settlement:basis-1:v2",
        }

    @patch("hr_external.integrations.hr15.ExternalSettlementInputService")
    def test_success_returns_hr15_receipt_without_salary_amount(self, service_cls):
        payload = self._payload()
        value = SimpleNamespace(
            id=uuid.uuid4(),
            source_version=2,
            content_hash="a" * 64,
            received_at=SimpleNamespace(isoformat=lambda: "2026-09-02T10:00:00+08:00"),
        )
        service_cls.return_value.receive.return_value = SimpleNamespace(value=value, created=True)

        result = SettlementProvider().notify_settlement_basis(**payload)

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data["receiptId"], str(value.id))
        self.assertNotIn("amount", result.data)
        service_cls.return_value.receive.assert_called_once_with(
            engagement_id=payload["engagement_id"],
            period="2026-09",
            source_version=2,
            verified_workload="60.00",
            eligible_items=[{"taskId": "TASK-1", "quantity": 60}],
            policy_ref="EXT-LECTURE-2026",
            idempotency_key="hr08-settlement:basis-1:v2",
        )

    @patch("hr_external.integrations.hr15.ExternalSettlementInputService")
    def test_hr15_validation_failure_remains_explicitly_unavailable(self, service_cls):
        service_cls.return_value.receive.side_effect = ExternalSettlementInputError(
            "EXTERNAL_SETTLEMENT_PERIOD_INVALID", "period must use YYYY-MM"
        )
        result = SettlementProvider().notify_settlement_basis(**self._payload())
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "EXTERNAL_SETTLEMENT_PERIOD_INVALID")
