import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import participant_api
from hr_exit.services.participant_service import ExitParticipantError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class ExitParticipantApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.effect_id = uuid.uuid4()

    @staticmethod
    def _result(status="SUCCESS", effect_status="SUCCESS", error=""):
        return SimpleNamespace(
            effect=SimpleNamespace(id=uuid.uuid4(), status=effect_status),
            participant="IAM",
            status=status,
            receipt={"provider": "iam-authority"} if status == "SUCCESS" else {},
            error=error,
        )

    @patch("hr_exit.participant_api.ExitParticipantService")
    @patch("hr_exit.participant_api.resolve_request_tenant", return_value=77)
    def test_execute_uses_effect_permission_and_returns_success_receipt(
        self, tenant_resolver, service_cls
    ):
        result = self._result()
        result.effect.id = self.effect_id
        service_cls.return_value.execute.return_value = result
        request = self.factory.post(
            f"/api/v1/hr/exit/effects/{self.effect_id}/participants/IAM/execute/"
        )
        request.user = UserStub()

        response = participant_api.execute_participant(
            request, self.effect_id, "IAM"
        )

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=participant_api.EFFECT_PERMISSION
        )
        service_cls.assert_called_once_with(77, actor_user_id=88)
        service_cls.return_value.execute.assert_called_once_with(
            effect_id=self.effect_id,
            participant="IAM",
        )
        self.assertIn(b"iam-authority", response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_exit.participant_api.ExitParticipantService")
    @patch("hr_exit.participant_api.resolve_request_tenant", return_value=77)
    def test_unavailable_or_failed_provider_returns_202_not_fake_200(
        self, _tenant, service_cls
    ):
        result = self._result(
            status="UNAVAILABLE",
            effect_status="PARTIAL_FAILED",
            error="no formal IAM provider is registered",
        )
        result.effect.id = self.effect_id
        service_cls.return_value.execute.return_value = result
        request = self.factory.post("/participant")
        request.user = UserStub()

        response = participant_api.execute_participant(
            request, self.effect_id, "IAM"
        )

        self.assertEqual(response.status_code, 202)
        self.assertIn(b"UNAVAILABLE", response.content)
        self.assertIn(b"PARTIAL_FAILED", response.content)

    @patch("hr_exit.participant_api.ExitParticipantService")
    @patch("hr_exit.participant_api.resolve_request_tenant", return_value=77)
    def test_core_not_effective_maps_to_conflict(self, _tenant, service_cls):
        service_cls.return_value.execute.side_effect = ExitParticipantError(
            "EXIT_EFFECT_CORE_NOT_EFFECTIVE",
            "HR03 must succeed first",
        )
        request = self.factory.post("/participant")
        request.user = UserStub()

        response = participant_api.execute_participant(
            request, self.effect_id, "IAM"
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"EXIT_EFFECT_CORE_NOT_EFFECTIVE", response.content)

    @patch("hr_exit.participant_api.ExitParticipantService")
    @patch("hr_exit.participant_api.resolve_request_tenant", return_value=77)
    def test_reconcile_returns_202_while_any_required_participant_is_not_success(
        self, _tenant, service_cls
    ):
        success = self._result(status="SUCCESS", effect_status="APPLYING")
        unavailable = SimpleNamespace(
            effect=SimpleNamespace(id=self.effect_id, status="PARTIAL_FAILED"),
            participant="ARCHIVE",
            status="UNAVAILABLE",
            receipt={},
            error="archive unavailable",
        )
        service_cls.return_value.reconcile.return_value = [success, unavailable]
        request = self.factory.post("/reconcile")
        request.user = UserStub()

        response = participant_api.reconcile_participants(request, self.effect_id)

        self.assertEqual(response.status_code, 202)
        self.assertIn(b"ARCHIVE", response.content)
        self.assertIn(b"UNAVAILABLE", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get("/participant")
        request.user = UserStub()
        response = participant_api.execute_participant(
            request, self.effect_id, "IAM"
        )
        self.assertEqual(response.status_code, 405)
