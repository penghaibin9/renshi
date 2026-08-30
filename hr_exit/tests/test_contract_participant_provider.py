import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_contracts.models import HrContractAgreement
from hr_exit.services.contract_participant_provider import (
    exit_contract_participant_provider,
)
from hr_exit.services.participant_service import ExitParticipantUnavailable


class ContractParticipantProviderTests(SimpleTestCase):
    def setUp(self):
        self.case = SimpleNamespace(employment_relationship_id=uuid.uuid4())
        self.effect = SimpleNamespace(
            id=uuid.uuid4(), idempotency_key="exit:contract-clearance:1"
        )

    @staticmethod
    def _agreement(status, number):
        return SimpleNamespace(
            id=uuid.uuid4(),
            agreement_no=number,
            status=status,
            current_version_no=2,
        )

    @patch("hr_exit.services.contract_participant_provider.HrContractAgreement.objects")
    def test_open_hr07_contract_is_retryable_unavailable(self, objects):
        objects.filter.return_value.order_by.return_value = [
            self._agreement(HrContractAgreement.Status.ACTIVE, "HT-001")
        ]

        with self.assertRaises(ExitParticipantUnavailable) as cm:
            exit_contract_participant_provider(
                tenant_id=77, case=self.case, effect=self.effect, actor_user_id=9
            )

        self.assertIn("HT-001", str(cm.exception))
        objects.filter.assert_called_once_with(
            tenant_id=77,
            employment_relationship_id=self.case.employment_relationship_id,
        )

    @patch("hr_exit.services.contract_participant_provider.HrContractAgreement.objects")
    def test_closed_contracts_return_stable_authority_receipt(self, objects):
        agreement = self._agreement(HrContractAgreement.Status.TERMINATED, "HT-001")
        objects.filter.return_value.order_by.return_value = [agreement]

        first = exit_contract_participant_provider(
            tenant_id=77, case=self.case, effect=self.effect, actor_user_id=9
        )
        second = exit_contract_participant_provider(
            tenant_id=77, case=self.case, effect=self.effect, actor_user_id=9
        )

        self.assertEqual(first, second)
        self.assertEqual(first["provider"], "hr07.contract-clearance.1")
        self.assertEqual(first["agreementCount"], 1)
        self.assertEqual(len(first["evidenceHash"]), 64)

    @patch("hr_exit.services.contract_participant_provider.HrContractAgreement.objects")
    def test_no_formal_contract_is_explicit_zero_count_not_fake_agreement(self, objects):
        objects.filter.return_value.order_by.return_value = []
        receipt = exit_contract_participant_provider(
            tenant_id=77, case=self.case, effect=self.effect
        )
        self.assertEqual(receipt["agreementCount"], 0)
        self.assertEqual(receipt["agreements"], [])
