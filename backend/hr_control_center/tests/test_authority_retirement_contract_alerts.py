from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import AUTHORITY_ONLY
from hr_control_center.services.alert_service import (
    ALERT_RULE_CONFIG,
    _rule_authority_contract_expire_90d,
)


class CanonicalAuthorityAlertTests(SimpleTestCase):
    @patch("hr_contracts.services.alert_escalation.CanonicalContractExpiryService")
    def test_contract_alert_previews_sealed_hr07_policy_without_writes(self, service):
        service.return_value.scan.return_value = {
            "blocked": 0,
            "actions": [
                {
                    "agreementId": "agreement-1",
                    "agreementNo": "HT-2026-001",
                    "dueDate": "2026-09-20",
                    "stage": "EXPIRING",
                    "severity": "HIGH",
                    "policyVersion": "CN-2026-v1",
                }
            ],
        }
        context = HrRequestContext(
            tenant_id=77,
            authority_mode=AUTHORITY_ONLY,
            as_of=None,
        )

        result = _rule_authority_contract_expire_90d(
            context, ALERT_RULE_CONFIG["contract.expire_90d"]
        )

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.items[0].source_object_type, "hr07_contract_agreement")
        self.assertEqual(
            result.items[0].payload["dataBasis"], "AUTHORITATIVE_EFFECTIVE_FACT"
        )
        service.return_value.scan.assert_called_once_with(
            as_of=context.today(), dry_run=True, limit=5000
        )

    def test_retirement_authority_alert_requires_complete_daily_scheduled_prechecks(self):
        source = (
            Path(__file__).resolve().parents[1] / "services" / "alert_service.py"
        ).read_text(encoding="utf-8")
        section = source[
            source.index("def _rule_authority_retirement_within_180d") :
            source.index("def _rule_contract_expire_90d")
        ]
        self.assertIn('idempotency_key__startswith=f"scheduled:', section)
        self.assertIn("covered != active_count", section)
        self.assertIn("HR16_RETIREMENT_PRECHECK_INCOMPLETE", section)
        self.assertIn("DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT", section)
