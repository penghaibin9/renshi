import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_title import api


class _UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr13ReviewAssignmentReplacementApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.assignment_id = uuid.uuid4()
        self.replacement_id = uuid.uuid4()
        self.case_id = uuid.uuid4()
        self.round_id = uuid.uuid4()
        self.reviewer_id = uuid.uuid4()

    def _request(self, permission):
        request = self.factory.post(
            f"/api/v1/hr/titles/review-assignments/{self.assignment_id}/replace/",
            data=json.dumps(
                {
                    "replacementNo": "ASN-REPLACEMENT",
                    "reviewerStaffId": str(self.reviewer_id),
                    "reviewerRole": "COMMITTEE",
                    "reasonCode": "IDENTITY_CORRECTION",
                    "reason": "评委身份录入错误",
                    "correlationId": "fix-001",
                }
            ),
            content_type="application/json",
        )
        request.user = _UserStub({permission})
        return request

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    def test_panel_permission_alone_cannot_replace_evidence(self, _allowed, _tenant):
        response = api.replace_review_assignment(
            self._request(api.PANEL_PERMISSION), self.assignment_id
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(api.PANEL_CORRECT_PERMISSION.encode(), response.content)

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    @patch("hr_title.api.TitlePanelService")
    def test_correction_permission_appends_replacement(self, service_cls, _allowed, _tenant):
        assignment = SimpleNamespace(
            id=self.replacement_id,
            assignment_no="ASN-REPLACEMENT",
            application_case_id=self.case_id,
            review_round_id=self.round_id,
            reviewer_staff_id=self.reviewer_id,
            reviewer_role="COMMITTEE",
            status="ASSIGNED",
            supersedes_assignment_id=self.assignment_id,
            replacement_reason_code="IDENTITY_CORRECTION",
            replacement_reason="评委身份录入错误",
            responded_at=None,
        )
        service_cls.return_value.replace_assignment.return_value = SimpleNamespace(
            assignment=assignment, created=True
        )
        response = api.replace_review_assignment(
            self._request(api.PANEL_CORRECT_PERMISSION), self.assignment_id
        )
        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(
            7, actor_user_id=88, correlation_id="fix-001"
        )
        service_cls.return_value.replace_assignment.assert_called_once_with(
            self.assignment_id,
            replacement_no="ASN-REPLACEMENT",
            reviewer_staff_id=str(self.reviewer_id),
            reviewer_role="COMMITTEE",
            reason_code="IDENTITY_CORRECTION",
            reason="评委身份录入错误",
        )
        payload = json.loads(response.content)
        self.assertTrue(payload["data"]["conflictRevalidationRequired"])
        self.assertTrue(payload["data"]["created"])
