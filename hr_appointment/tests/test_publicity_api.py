import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from hr_appointment import api
from hr_appointment.services.publicity_service import AppointmentPublicityError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr14PublicityApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()
        self.publicity_id = uuid.uuid4()
        self.objection_id = uuid.uuid4()

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_review_permission_alone_cannot_open_publicity(self, _allowed, _tenant):
        now = timezone.now()
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/publicity/",
            data=json.dumps(
                {
                    "rankingResultId": str(uuid.uuid4()),
                    "publicityNo": "PUB-1",
                    "startAt": now.isoformat(),
                    "endAt": (now + timedelta(days=5)).isoformat(),
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.REVIEW_PERMISSION})

        response = api.open_publicity(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.PUBLICITY_PERMISSION.encode(), response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentPublicityService")
    def test_open_publicity_uses_resolved_tenant_actor_and_iso_window(
        self, service_cls, _allowed, _tenant
    ):
        now = timezone.now().replace(microsecond=0)
        ranking_id = uuid.uuid4()
        record = SimpleNamespace(
            id=self.publicity_id,
            publicity_no="PUB-2",
            application_case_id=self.case_id,
            ranking_result_id=ranking_id,
            attempt_no=1,
            start_at=now,
            end_at=now + timedelta(days=5),
            status="OPEN",
        )
        service_cls.return_value.open_publicity.return_value = SimpleNamespace(
            publicity=record,
            case=SimpleNamespace(status="PUBLICITY"),
            created=True,
        )
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/publicity/",
            data=json.dumps(
                {
                    "rankingResultId": str(ranking_id),
                    "publicityNo": "PUB-2",
                    "startAt": now.isoformat(),
                    "endAt": (now + timedelta(days=5)).isoformat(),
                    "noticeSnapshot": {"rank": 1},
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.PUBLICITY_PERMISSION})

        response = api.open_publicity(request, self.case_id)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        kwargs = service_cls.return_value.open_publicity.call_args.kwargs
        self.assertEqual(kwargs["case_id"], self.case_id)
        self.assertEqual(kwargs["ranking_result_id"], str(ranking_id))
        self.assertEqual(kwargs["publicity_no"], "PUB-2")
        self.assertEqual(kwargs["notice_snapshot"], {"rank": 1})
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(b'"caseStatus": "PUBLICITY"', response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentPublicityService")
    def test_submit_objection_preserves_evidence_and_submitter(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.submit_objection.return_value = SimpleNamespace(
            id=self.objection_id,
            objection_no="OBJ-1",
            publicity_id=self.publicity_id,
            status="RECEIVED",
        )
        request = self.factory.post(
            f"/api/v1/hr/appointments/publicities/{self.publicity_id}/objections/",
            data=json.dumps(
                {
                    "objectionNo": "OBJ-1",
                    "contentSummary": "材料事实存在疑点",
                    "submitterRef": "STAFF-9",
                    "evidenceRefs": ["file:proof-1"],
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.PUBLICITY_PERMISSION})

        response = api.submit_publicity_objection(request, self.publicity_id)

        self.assertEqual(response.status_code, 201)
        service_cls.return_value.submit_objection.assert_called_once_with(
            publicity_id=self.publicity_id,
            objection_no="OBJ-1",
            content_summary="材料事实存在疑点",
            submitter_ref="STAFF-9",
            evidence_refs=["file:proof-1"],
        )
        self.assertIn(b"RECEIVED", response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentPublicityService")
    def test_pending_objection_close_conflict_maps_to_409(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.close_publicity.side_effect = AppointmentPublicityError(
            "APPOINTMENT_PUBLICITY_OBJECTION_PENDING",
            "all objections must be resolved before publicity can close",
        )
        request = self.factory.post(
            f"/api/v1/hr/appointments/publicities/{self.publicity_id}/close/"
        )
        request.user = UserStub({api.PUBLICITY_PERMISSION})

        response = api.close_publicity(request, self.publicity_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"APPOINTMENT_PUBLICITY_OBJECTION_PENDING", response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentPublicityService")
    def test_resolve_and_cancel_preserve_decision_reason(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.resolve_objection.return_value = SimpleNamespace(
            id=self.objection_id,
            objection_no="OBJ-2",
            status="NOT_UPHELD",
            resolution_note="复核无误",
        )
        resolve_request = self.factory.post(
            f"/api/v1/hr/appointments/publicity-objections/{self.objection_id}/resolve/",
            data=json.dumps({"outcome": "NOT_UPHELD", "resolutionNote": "复核无误"}),
            content_type="application/json",
        )
        resolve_request.user = UserStub({api.PUBLICITY_PERMISSION})
        response = api.resolve_publicity_objection(resolve_request, self.objection_id)
        self.assertEqual(response.status_code, 200)
        service_cls.return_value.resolve_objection.assert_called_once_with(
            self.objection_id,
            outcome="NOT_UPHELD",
            resolution_note="复核无误",
        )

        service_cls.return_value.cancel_publicity.return_value = SimpleNamespace(
            id=self.publicity_id,
            status="CANCELLED",
        )
        cancel_request = self.factory.post(
            f"/api/v1/hr/appointments/publicities/{self.publicity_id}/cancel/",
            data=json.dumps({"reason": "异议成立，退回更正"}),
            content_type="application/json",
        )
        cancel_request.user = UserStub({api.PUBLICITY_PERMISSION})
        response = api.cancel_publicity(cancel_request, self.publicity_id)
        self.assertEqual(response.status_code, 200)
        service_cls.return_value.cancel_publicity.assert_called_once_with(
            self.publicity_id, reason="异议成立，退回更正"
        )

    def test_non_post_is_rejected(self):
        request = self.factory.get(
            f"/api/v1/hr/appointments/publicities/{self.publicity_id}/close/"
        )
        request.user = UserStub({api.PUBLICITY_PERMISSION})
        response = api.close_publicity(request, self.publicity_id)
        self.assertEqual(response.status_code, 405)
