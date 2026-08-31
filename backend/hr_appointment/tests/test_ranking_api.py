import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_appointment import api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr14RankingApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_view_permission_alone_cannot_finalize_ranking(self, _allowed, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/ranking-result/",
            data=json.dumps(
                {
                    "rankingNo": "RK-1",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.READ_PERMISSION})

        response = api.ranking_result(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.REVIEW_PERMISSION.encode(), response.content)

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    @patch("hr_appointment.api.AppointmentRankingService")
    def test_review_permission_uses_resolved_tenant_and_actor(
        self, service_cls, _allowed, _tenant
    ):
        ranking = SimpleNamespace(
            id=uuid.uuid4(),
            ranking_no="RK-2",
            application_case_id=self.case_id,
            batch_no="BATCH-1",
            position_instance_id=101,
            attempt_no=1,
            total_score="91.2500",
            rank_no=1,
            outcome="SELECTED",
        )
        service_cls.return_value.finalize.return_value = SimpleNamespace(
            ranking=ranking,
            case=SimpleNamespace(status="PROPOSED"),
            created=True,
        )
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/ranking-result/",
            data=json.dumps(
                {
                    "rankingNo": "RK-2",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.REVIEW_PERMISSION})

        response = api.ranking_result(request, self.case_id)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.finalize.assert_called_once_with(
            case_id=self.case_id,
            ranking_no="RK-2",
        )
        self.assertIn(b'"caseStatus": "PROPOSED"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_authoritative_ranking_fields_are_rejected(self, _allowed, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/appointments/applications/{self.case_id}/ranking-result/",
            data=json.dumps(
                {
                    "rankingNo": "RK-FAKE",
                    "totalScore": "100",
                    "rankNo": 1,
                    "outcome": "SELECTED",
                    "scoreSnapshot": {"forged": True},
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.REVIEW_PERMISSION})

        response = api.ranking_result(request, self.case_id)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"APPOINTMENT_RANKING_CLIENT_AUTHORITY_FORBIDDEN", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get(
            f"/api/v1/hr/appointments/applications/{self.case_id}/ranking-result/"
        )
        request.user = UserStub({api.REVIEW_PERMISSION})
        response = api.ranking_result(request, self.case_id)
        self.assertEqual(response.status_code, 405)
