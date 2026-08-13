import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_title import api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr13QualificationApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    def test_view_permission_alone_cannot_write_review(self, _allowed, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/titles/applications/{self.case_id}/qualification-decision/",
            data=json.dumps({"decisionNo": "QD-1", "decision": "ELIGIBLE"}),
            content_type="application/json",
        )
        request.user = UserStub({api.READ_PERMISSION})

        response = api.qualification_decision(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.REVIEW_PERMISSION.encode(), response.content)

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    @patch("hr_title.api.TitleQualificationService")
    def test_review_permission_uses_resolved_tenant_and_actor(
        self, service_cls, _allowed, _tenant
    ):
        decision = SimpleNamespace(
            id=uuid.uuid4(),
            decision_no="QD-2",
            application_case_id=self.case_id,
            attempt_no=1,
            decision="ELIGIBLE",
            reason_code="",
            reason="",
        )
        service_cls.return_value.decide.return_value = SimpleNamespace(
            decision=decision,
            case=SimpleNamespace(status="ELIGIBLE"),
            created=True,
        )
        request = self.factory.post(
            f"/api/v1/hr/titles/applications/{self.case_id}/qualification-decision/",
            data=json.dumps({"decisionNo": "QD-2", "decision": "ELIGIBLE"}),
            content_type="application/json",
        )
        request.user = UserStub({api.REVIEW_PERMISSION})

        response = api.qualification_decision(request, self.case_id)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.decide.assert_called_once_with(
            case_id=self.case_id,
            decision_no="QD-2",
            decision="ELIGIBLE",
            reason_code="",
            reason="",
        )
        self.assertIn(b'"caseStatus": "ELIGIBLE"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_non_post_is_rejected(self):
        request = self.factory.get(
            f"/api/v1/hr/titles/applications/{self.case_id}/qualification-decision/"
        )
        request.user = UserStub({api.REVIEW_PERMISSION})
        response = api.qualification_decision(request, self.case_id)
        self.assertEqual(response.status_code, 405)
