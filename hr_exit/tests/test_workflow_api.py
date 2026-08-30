import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import api
from hr_exit.services.effect_service import ExitEffectError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr16WorkflowApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    def _post(self, path, payload=None, *, permissions=()):
        request = self.factory.post(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
        )
        request.user = UserStub(permissions)
        return request

    def _case(self, *, status="DRAFT"):
        return SimpleNamespace(
            id=self.case_id,
            case_no="EXIT-2026-001",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type="RESIGNATION",
            status=status,
            requested_date=date(2026, 8, 13),
            last_working_date=date(2026, 8, 31),
            planned_employment_end_date=date(2026, 9, 1),
            planned_access_end_at=None,
        )

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_handover_permission_cannot_approve_exit_case(self, _allowed, _tenant):
        request = self._post(
            f"/api/v1/hr/exit/cases/{self.case_id}/approve/",
            permissions={api.HANDOVER_PERMISSION},
        )

        response = api.approve_case(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(api.MANAGE_PERMISSION.encode(), response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_manage_permission_cannot_execute_hr03_exit_effect(self, _allowed, _tenant):
        request = self._post(
            f"/api/v1/hr/exit/cases/{self.case_id}/apply-effect/",
            {
                "factNo": "EXIT-F-001",
                "idempotencyKey": "exit:7:case:001",
            },
            permissions={api.MANAGE_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(api.EFFECT_PERMISSION.encode(), response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitCaseService")
    def test_create_case_passes_tenant_actor_and_normalized_inputs(
        self, service_cls, _allowed, _tenant
    ):
        case = self._case()
        service_cls.return_value.create_draft.return_value = case
        request = self._post(
            "/api/v1/hr/exit/cases/",
            {
                "caseNo": "EXIT-2026-001",
                "personId": str(case.person_id),
                "employmentRelationshipId": str(case.employment_relationship_id),
                "exitType": "RESIGNATION",
                "requestedDate": "2026-08-13",
                "lastWorkingDate": "2026-08-31",
                "plannedEmploymentEndDate": "2026-09-01",
            },
            permissions={api.MANAGE_PERMISSION},
        )

        response = api.create_case(request)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        payload = service_cls.return_value.create_draft.call_args.args[0]
        self.assertEqual(payload.case_no, "EXIT-2026-001")
        self.assertEqual(payload.person_id, case.person_id)
        self.assertEqual(payload.employment_relationship_id, case.employment_relationship_id)
        self.assertEqual(payload.requested_date, date(2026, 8, 13))
        self.assertEqual(payload.planned_employment_end_date, date(2026, 9, 1))
        self.assertIn(b'"schemaVersion": "hr16.exit-case.1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitCaseService")
    def test_case_transition_uses_manage_authority(self, service_cls, _allowed, _tenant):
        case = self._case(status="APPROVED")
        service_cls.return_value.approve.return_value = case
        request = self._post(
            f"/api/v1/hr/exit/cases/{self.case_id}/approve/",
            permissions={api.MANAGE_PERMISSION},
        )

        response = api.approve_case(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.approve.assert_called_once_with(self.case_id)
        self.assertIn(b'"status": "APPROVED"', response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitEffectService")
    def test_effect_endpoint_returns_202_for_pending_provider_effect(
        self, service_cls, _allowed, _tenant
    ):
        fact = SimpleNamespace(
            id=uuid.uuid4(),
            fact_no="EXIT-F-001",
            status="EFFECT_PENDING",
            effect_receipt_json={},
        )
        effect = SimpleNamespace(
            id=uuid.uuid4(),
            effect_version=1,
            status="FAILED",
            hr03_status="FAILED",
            hr07_status="NOT_REQUIRED",
            hr14_status="NOT_REQUIRED",
            iam_status="NOT_REQUIRED",
            asset_status="NOT_REQUIRED",
            settlement_status="NOT_REQUIRED",
            finance_status="NOT_REQUIRED",
            archive_status="NOT_REQUIRED",
        )
        service_cls.return_value.apply.return_value = SimpleNamespace(
            fact=fact,
            effect=effect,
            effective=False,
            error="HR03 write failed",
        )
        request = self._post(
            f"/api/v1/hr/exit/cases/{self.case_id}/apply-effect/",
            {
                "factNo": " EXIT-F-001 ",
                "idempotencyKey": "exit:7:case:001",
                "reasonCode": "RESIGNATION",
                "requiredParticipants": [],
            },
            permissions={api.EFFECT_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 202)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.apply.assert_called_once_with(
            case_id=self.case_id,
            fact_no=" EXIT-F-001 ",
            idempotency_key="exit:7:case:001",
            reason_code="RESIGNATION",
            correlation_id="",
            required_participants=[],
        )
        self.assertIn(b'"effective": false', response.content)
        self.assertIn(b"HR03 write failed", response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.api.ExitEffectService")
    def test_effect_conflict_maps_to_409(self, service_cls, _allowed, _tenant):
        service_cls.return_value.apply.side_effect = ExitEffectError(
            "EXIT_EFFECT_IDEMPOTENCY_CONFLICT",
            "fact_no already belongs to a different exit payload",
        )
        request = self._post(
            f"/api/v1/hr/exit/cases/{self.case_id}/apply-effect/",
            {"factNo": "EXIT-F-001", "idempotencyKey": "idem-1"},
            permissions={api.EFFECT_PERMISSION},
        )

        response = api.apply_effect(request, self.case_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"EXIT_EFFECT_IDEMPOTENCY_CONFLICT", response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_create_case_rejects_invalid_uuid_and_effect_rejects_participant_shape(
        self, _allowed, _tenant
    ):
        bad_case = self._post(
            "/api/v1/hr/exit/cases/",
            {
                "caseNo": "EXIT-X",
                "personId": "not-a-uuid",
                "employmentRelationshipId": str(uuid.uuid4()),
                "exitType": "RESIGNATION",
            },
            permissions={api.MANAGE_PERMISSION},
        )
        response = api.create_case(bad_case)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_FIELD", response.content)

        bad_effect = self._post(
            f"/api/v1/hr/exit/cases/{self.case_id}/apply-effect/",
            {
                "factNo": "EXIT-F-001",
                "idempotencyKey": "idem-1",
                "requiredParticipants": "IAM",
            },
            permissions={api.EFFECT_PERMISSION},
        )
        response = api.apply_effect(bad_effect, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"EXIT_EFFECT_PARTICIPANTS_INVALID", response.content)
