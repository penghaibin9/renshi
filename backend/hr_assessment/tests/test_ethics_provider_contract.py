"""HR12 师德 Provider 使用 HR03 正式处分事实，不读取投诉或草稿。"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import EthicsFactProvider
from hr_assessment.service.evidence import ProviderCollectionOrchestrator


class EthicsProviderContractTests(SimpleTestCase):
    def test_capability_reports_formal_ethics_source_available(self):
        self.assertEqual(
            ProviderCollectionOrchestrator().capability_status()["ethicsFact"],
            ProviderStatus.OK.value,
        )

    @patch("hr_staff.public.get_formal_ethics_evidence")
    def test_formal_fact_is_returned_from_source_owned_contract(self, get_evidence):
        staff_id = uuid.uuid4()
        get_evidence.return_value = SimpleNamespace(
            rows=(SimpleNamespace(snapshot=lambda: {"staffId": str(staff_id)}),),
            missing_staff_ids=(),
        )
        result = EthicsFactProvider().fetch(
            ProviderContext(tenant_id=7, ids=[staff_id])
        )
        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data, [{"staffId": str(staff_id)}])
        self.assertEqual(result.source_version, "hr03-formal-discipline-evidence-v1")
        get_evidence.assert_called_once()
        self.assertEqual(get_evidence.call_args.kwargs["tenant_id"], 7)
        self.assertEqual(get_evidence.call_args.kwargs["staff_ids"], [staff_id])

    @patch("hr_staff.public.get_formal_ethics_evidence")
    def test_missing_staff_is_partial_not_fake_empty_ok(self, get_evidence):
        staff_id = uuid.uuid4()
        get_evidence.return_value = SimpleNamespace(
            rows=(),
            missing_staff_ids=(staff_id,),
        )
        result = EthicsFactProvider().fetch(
            ProviderContext(tenant_id=7, ids=[staff_id])
        )
        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertIn("ETHICS_BASIS_UNAVAILABLE", result.error_message)
