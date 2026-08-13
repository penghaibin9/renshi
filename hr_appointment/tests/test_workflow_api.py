import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from hr_appointment import application_api, batch_api
from hr_appointment.services.batch_service import AppointmentBatchError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr14WorkflowApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.batch_id = uuid.uuid4()
        self.case_id = uuid.uuid4()
        self.policy_id = uuid.uuid4()
        self.person_id = uuid.uuid4()

    @patch("hr_appointment.batch_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.batch_api.AppointmentBatchService")
    def test_create_batch_parses_window_and_uses_review_permission(
        self, service_cls, _tenant
    ):
        now = timezone.now().replace(microsecond=0)
        batch = SimpleNamespace(
            id=self.batch_id,
            batch_no="B-2026-01",
            name="2026 岗位竞聘",
            business_type="COMPETITIVE_APPOINTMENT",
            policy_version_id=self.policy_id,
            target_categories_json=["PROFESSIONAL_TECHNICAL"],
            target_levels_json=["PT-7"],
            application_from=now,
            application_to=now + timedelta(days=5),
            status="DRAFT",
        )
        service_cls.return_value.create_draft.return_value = batch
        request = self.factory.post(
            "/api/v1/hr/appointments/batches/",
            data=json.dumps(
                {
                    "batchNo": batch.batch_no,
                    "name": batch.name,
                    "policyVersionId": str(self.policy_id),
                    "targetCategories": batch.target_categories_json,
                    "targetLevels": batch.target_levels_json,
                    "applicationFrom": now.isoformat(),
                    "applicationTo": (now + timedelta(days=5)).isoformat(),
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({batch_api.REVIEW_PERMISSION})

        response = batch_api.create_batch(request)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        payload = service_cls.return_value.create_draft.call_args.args[0]
        self.assertEqual(payload.batch_no, "B-2026-01")
        self.assertEqual(payload.application_from, now)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_appointment.batch_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.batch_api.AppointmentBatchService")
    def test_unresolved_eligibility_maps_batch_review_start_to_conflict(
        self, service_cls, _tenant
    ):
        service_cls.return_value.begin_review.side_effect = AppointmentBatchError(
            "APPOINTMENT_ELIGIBILITY_INCOMPLETE",
            "all submitted applications must finish eligibility review",
        )
        request = self.factory.post(
            f"/api/v1/hr/appointments/batches/{self.batch_id}/review/start/"
        )
        request.user = UserStub({batch_api.REVIEW_PERMISSION})

        response = batch_api.begin_review(request, self.batch_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"APPOINTMENT_ELIGIBILITY_INCOMPLETE", response.content)

    @patch("hr_appointment.application_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.application_api.AppointmentApplicationService")
    def test_create_application_uses_frozen_identity_payload(
        self, service_cls, _tenant
    ):
        case = SimpleNamespace(
            id=self.case_id,
            case_no="CASE-001",
            person_id=self.person_id,
            policy_version_id=self.policy_id,
            position_instance_id=1001,
            batch_no="B-2026-01",
            requested_level_code="PT-7",
            status="DRAFT",
        )
        service_cls.return_value.create_draft.return_value = case
        request = self.factory.post(
            "/api/v1/hr/appointments/applications/",
            data=json.dumps(
                {
                    "caseNo": case.case_no,
                    "personId": str(self.person_id),
                    "policyVersionId": str(self.policy_id),
                    "positionInstanceId": 1001,
                    "batchNo": case.batch_no,
                    "requestedLevelCode": "PT-7",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({application_api.REVIEW_PERMISSION})

        response = application_api.create_application(request)

        self.assertEqual(response.status_code, 201)
        payload = service_cls.return_value.create_draft.call_args.args[0]
        self.assertEqual(payload.person_id, self.person_id)
        self.assertEqual(payload.policy_version_id, self.policy_id)
        self.assertEqual(payload.position_instance_id, 1001)
        self.assertIn(b'"status": "DRAFT"', response.content)

    @patch("hr_appointment.application_api.resolve_request_tenant", return_value=7)
    def test_invalid_application_identity_is_rejected_before_service(self, _tenant):
        request = self.factory.post(
            "/api/v1/hr/appointments/applications/",
            data=json.dumps(
                {
                    "caseNo": "CASE-BAD",
                    "personId": "not-a-uuid",
                    "policyVersionId": str(self.policy_id),
                    "positionInstanceId": 0,
                    "batchNo": "B-2026-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({application_api.REVIEW_PERMISSION})

        response = application_api.create_application(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"APPOINTMENT_APPLICATION_IDENTITY_INVALID", response.content)
