import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit.archive_registry import PERM_EXIT_FACT_CORRECT, PERM_EXIT_FACT_REVOKE
from hr_exit.fact_api import correct_exit_fact, revoke_exit_fact
from hr_exit.models import ExitFact


class ExitFactEvidenceApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.fact_id = uuid.UUID("00000000-0000-0000-0000-000000000401")

    def _user(self):
        return SimpleNamespace(id=9, is_authenticated=True, is_superuser=False)

    def _fact(self, *, status=ExitFact.Status.REVISED):
        return SimpleNamespace(
            id=uuid.UUID("00000000-0000-0000-0000-000000000402"),
            fact_no="EXIT-001-R1",
            person_id=uuid.UUID("00000000-0000-0000-0000-000000000201"),
            employment_relationship_id=uuid.UUID(
                "00000000-0000-0000-0000-000000000301"
            ),
            source_case_id=uuid.UUID("00000000-0000-0000-0000-000000000101"),
            exit_type="RESIGNATION",
            employment_end_date=date(2026, 9, 1),
            last_working_date=date(2026, 8, 30),
            access_end_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            status=status,
            effect_receipt_json={"hr03RelationshipStatus": "ENDED"},
            supersedes_fact_id=self.fact_id,
            change_reason="DATE_CORRECTION",
            evidence_ref="doc://correction/001",
            content_hash="a" * 64,
            sealed_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )

    @patch("hr_exit.fact_api.ExitFactCorrectionService")
    @patch("hr_exit.fact_api.resolve_request_tenant", return_value=77)
    def test_correct_uses_dedicated_permission_and_returns_seal_evidence(
        self, resolve_tenant, service_cls
    ):
        service_cls.return_value.correct.return_value = self._fact()
        request = self.factory.post(
            "/api/v1/hr/exit/exit-facts/x/correct/",
            data=json.dumps(
                {
                    "factNo": "EXIT-001-R1",
                    "reasonCode": "DATE_CORRECTION",
                    "evidenceRef": "doc://correction/001",
                    "lastWorkingDate": "2026-08-30",
                }
            ),
            content_type="application/json",
            HTTP_X_CORRELATION_ID="corr-api-001",
        )
        request.user = self._user()

        response = correct_exit_fact(request, self.fact_id)

        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)["data"]
        self.assertEqual(data["contentHash"], "a" * 64)
        self.assertEqual(data["supersedesFactId"], str(self.fact_id))
        self.assertEqual(data["evidenceRef"], "doc://correction/001")
        resolve_tenant.assert_called_once_with(
            request, required_permission=PERM_EXIT_FACT_CORRECT
        )
        service_cls.assert_called_once_with(
            77, actor_user_id=9, correlation_id="corr-api-001"
        )

    @patch("hr_exit.fact_api.ExitFactCorrectionService")
    @patch("hr_exit.fact_api.resolve_request_tenant", return_value=77)
    def test_revoke_uses_separate_permission(self, resolve_tenant, service_cls):
        service_cls.return_value.revoke.return_value = self._fact(
            status=ExitFact.Status.REVOKED
        )
        request = self.factory.post(
            "/api/v1/hr/exit/exit-facts/x/revoke/",
            data=json.dumps(
                {
                    "factNo": "EXIT-001-X1",
                    "reasonCode": "LEGAL_REVOCATION",
                    "evidenceRef": "decision://revocation/001",
                }
            ),
            content_type="application/json",
        )
        request.user = self._user()

        response = revoke_exit_fact(request, self.fact_id)

        self.assertEqual(response.status_code, 201)
        resolve_tenant.assert_called_once_with(
            request, required_permission=PERM_EXIT_FACT_REVOKE
        )
        service_cls.return_value.revoke.assert_called_once()

    def test_identity_fields_are_rejected_before_service_write(self):
        request = self.factory.post(
            "/api/v1/hr/exit/exit-facts/x/correct/",
            data=json.dumps(
                {
                    "factNo": "EXIT-001-R1",
                    "reasonCode": "BAD_CHANGE",
                    "evidenceRef": "doc://correction/001",
                    "personId": str(uuid.uuid4()),
                }
            ),
            content_type="application/json",
        )
        request.user = self._user()
        with patch("hr_exit.fact_api.resolve_request_tenant", return_value=77):
            response = correct_exit_fact(request, self.fact_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "EXIT_FACT_IDENTITY_IMMUTABLE",
        )
