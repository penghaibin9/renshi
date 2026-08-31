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
    def test_create_batch_parses_windows_and_uses_manage_permission(
        self, service_cls, tenant_resolver
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
            publicity_from=now + timedelta(days=10),
            publicity_to=now + timedelta(days=15),
            version_no=1,
            content_hash="",
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
                    "publicityFrom": (now + timedelta(days=10)).isoformat(),
                    "publicityTo": (now + timedelta(days=15)).isoformat(),
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({batch_api.MANAGE_PERMISSION})

        response = batch_api.create_batch(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request, required_permission=batch_api.MANAGE_PERMISSION
        )
        service_cls.assert_called_once_with(7, actor_user_id=88)
        payload = service_cls.return_value.create_draft.call_args.args[0]
        self.assertEqual(payload.batch_no, "B-2026-01")
        self.assertEqual(payload.application_from, now)
        self.assertEqual(payload.publicity_from, now + timedelta(days=10))
        self.assertEqual(json.loads(response.content)["data"]["versionNo"], 1)
        self.assertEqual(response["ETag"], '"hr14-batch-v1"')
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_appointment.batch_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.batch_api.AppointmentBatchService")
    def test_unresolved_eligibility_maps_batch_review_start_to_conflict(
        self, service_cls, tenant_resolver
    ):
        service_cls.return_value.begin_review.side_effect = AppointmentBatchError(
            "APPOINTMENT_ELIGIBILITY_INCOMPLETE",
            "all submitted applications must finish eligibility review",
        )
        request = self.factory.post(
            f"/api/v1/hr/appointments/batches/{self.batch_id}/review/start/"
        )
        request.user = UserStub({batch_api.MANAGE_PERMISSION})

        response = batch_api.begin_review(request, self.batch_id)

        self.assertEqual(response.status_code, 409)
        tenant_resolver.assert_called_once_with(
            request, required_permission=batch_api.MANAGE_PERMISSION
        )
        self.assertIn(b"APPOINTMENT_ELIGIBILITY_INCOMPLETE", response.content)

    @patch("hr_appointment.application_api._resolve_applicant_person_id")
    @patch("hr_appointment.application_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.application_api.AppointmentApplicationService")
    def test_create_application_uses_application_permission_and_frozen_identity_payload(
        self, service_cls, tenant_resolver, resolve_self
    ):
        resolve_self.return_value = self.person_id
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
        request.user = UserStub({application_api.APPLICATION_PERMISSION})

        response = application_api.create_application(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request, required_permission=application_api.APPLICATION_PERMISSION
        )
        resolve_self.assert_called_once_with(request, 7)
        payload = service_cls.return_value.create_draft.call_args.args[0]
        self.assertEqual(payload.person_id, self.person_id)
        self.assertEqual(payload.policy_version_id, self.policy_id)
        self.assertEqual(payload.position_instance_id, 1001)
        self.assertIn(b'"status": "DRAFT"', response.content)

    @patch("hr_appointment.application_api.resolve_request_tenant", return_value=7)
    def test_invalid_application_identity_is_rejected_before_self_resolution(
        self, tenant_resolver
    ):
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
        request.user = UserStub({application_api.APPLICATION_PERMISSION})

        response = application_api.create_application(request)

        self.assertEqual(response.status_code, 400)
        tenant_resolver.assert_called_once_with(
            request, required_permission=application_api.APPLICATION_PERMISSION
        )
        self.assertIn(b"APPOINTMENT_APPLICATION_IDENTITY_INVALID", response.content)

    @patch("hr_appointment.application_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.application_api.AppointmentApplicationService")
    def test_eligibility_decision_uses_manage_permission(
        self, service_cls, tenant_resolver
    ):
        case = SimpleNamespace(
            id=self.case_id,
            case_no="CASE-ELIGIBLE",
            person_id=self.person_id,
            policy_version_id=self.policy_id,
            position_instance_id=1001,
            batch_no="B-2026-01",
            requested_level_code="PT-7",
            status="ELIGIBLE",
        )
        service_cls.return_value.pass_eligibility.return_value = case
        request = self.factory.post("/eligibility/pass")
        request.user = UserStub({application_api.MANAGE_PERMISSION})

        response = application_api.pass_eligibility(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=application_api.MANAGE_PERMISSION
        )

    @patch("hr_appointment.application_api.resolve_request_tenant", return_value=7)
    @patch("hr_appointment.application_api.AppointmentApplicationService")
    def test_start_review_keeps_review_permission(
        self, service_cls, tenant_resolver
    ):
        case = SimpleNamespace(
            id=self.case_id,
            case_no="CASE-REVIEW",
            person_id=self.person_id,
            policy_version_id=self.policy_id,
            position_instance_id=1001,
            batch_no="B-2026-01",
            requested_level_code="PT-7",
            status="UNDER_REVIEW",
        )
        service_cls.return_value.start_review.return_value = case
        request = self.factory.post("/review/start")
        request.user = UserStub({application_api.REVIEW_PERMISSION})

        response = application_api.start_review(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=application_api.REVIEW_PERMISSION
        )
