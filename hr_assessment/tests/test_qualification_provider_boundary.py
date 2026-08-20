"""HR12 -> HR09 provider boundary contracts."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.test import SimpleTestCase

from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import QualificationProvider


class QualificationProviderBoundaryTests(SimpleTestCase):
    @patch("hr_qualification.public.get_formal_credential_evidence")
    def test_provider_passes_canonical_staff_ids_and_as_of(self, get_evidence):
        staff_id = uuid.uuid4()
        row = SimpleNamespace(
            last_verified_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            snapshot=lambda: {
                "credential_id": str(uuid.uuid4()),
                "staff_id": str(staff_id),
                "status": "ACTIVE",
            },
        )
        get_evidence.return_value = SimpleNamespace(
            rows=(row,),
            uncertain_staff_ids=(),
        )

        result = QualificationProvider().fetch(
            ProviderContext(
                tenant_id=10001,
                ids=[staff_id],
                as_of=datetime(2026, 6, 30, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data[0]["staff_id"], str(staff_id))
        get_evidence.assert_called_once_with(
            tenant_id=10001,
            staff_ids=[staff_id],
            as_of=date(2026, 6, 30),
            source_version="v1",
        )

    @patch("hr_qualification.public.get_formal_credential_evidence")
    def test_uncertain_history_is_partial_not_fake_ok(self, get_evidence):
        staff_id = uuid.uuid4()
        get_evidence.return_value = SimpleNamespace(
            rows=(),
            uncertain_staff_ids=(staff_id,),
        )

        result = QualificationProvider().fetch(
            ProviderContext(tenant_id=10001, ids=[staff_id])
        )

        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertIn("CREDENTIAL_HISTORY_UNAVAILABLE", result.error_message)
