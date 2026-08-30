import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from hr_exit.services.external_participant_providers import (
    asset_participant_provider,
    finance_participant_provider,
    iam_participant_provider,
)
from hr_exit.services.participant_service import ExitParticipantUnavailable


class ExternalParticipantProviderTests(SimpleTestCase):
    def setUp(self):
        self.case = SimpleNamespace(
            id=uuid.uuid4(),
            case_no="EXIT-2026-001",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type="RESIGNATION",
            planned_employment_end_date=date(2026, 9, 1),
            planned_access_end_at=None,
        )
        self.effect = SimpleNamespace(
            id=uuid.uuid4(),
            effect_version=2,
            idempotency_key="exit:tenant-7:case-1:v2",
            correlation_id="corr-001",
        )

    def test_missing_credentials_is_explicit_unavailable(self):
        with self.assertRaises(ExitParticipantUnavailable) as cm:
            iam_participant_provider(
                tenant_id=7,
                case=self.case,
                effect=self.effect,
                actor_user_id=88,
            )
        self.assertIn("URL/token is not configured", str(cm.exception))

    @override_settings(
        HR16_EXIT_EXTERNAL_PROVIDERS={
            "ASSET": {
                "url": "https://asset.example.test/v1/exit-effects",
                "token": "sandbox-secret",
                "timeoutSeconds": 4,
            }
        }
    )
    @patch("hr_exit.services.external_participant_providers.request.urlopen")
    def test_sandbox_asset_call_has_idempotency_and_secret_free_receipt(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "receipt": {
                    "receiptId": "asset-receipt-1",
                    "idempotencyKey": self.effect.idempotency_key,
                    "openAssignments": 0,
                }
            }
        ).encode()
        urlopen.return_value = response

        receipt = asset_participant_provider(
            tenant_id=7,
            case=self.case,
            effect=self.effect,
            actor_user_id=88,
        )

        outbound = urlopen.call_args.args[0]
        payload = json.loads(outbound.data.decode())
        self.assertEqual(outbound.headers["X-idempotency-key"], self.effect.idempotency_key)
        self.assertEqual(payload["participant"], "ASSET")
        self.assertEqual(payload["case"]["employmentRelationshipId"], str(self.case.employment_relationship_id))
        self.assertEqual(receipt["receiptId"], "asset-receipt-1")
        self.assertNotIn("sandbox-secret", json.dumps(receipt))

    @override_settings(
        HR16_EXIT_EXTERNAL_PROVIDERS={
            "FINANCE": {
                "url": "https://finance.example.test/v1/exit-effects",
                "token": "sandbox-secret",
            }
        }
    )
    @patch("hr_exit.services.external_participant_providers.request.urlopen")
    def test_finance_rejects_mismatched_replay_receipt(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"receiptId": "finance-1", "idempotencyKey": "someone-else"}
        ).encode()
        urlopen.return_value = response

        with self.assertRaises(RuntimeError) as cm:
            finance_participant_provider(
                tenant_id=7,
                case=self.case,
                effect=self.effect,
                actor_user_id=88,
            )
        self.assertIn("idempotency receipt mismatch", str(cm.exception))
