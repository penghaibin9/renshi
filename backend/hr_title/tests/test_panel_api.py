import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_title import api
from hr_title.services.panel_service import TitlePanelError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr13PanelApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()
        self.round_id = uuid.uuid4()
        self.assignment_id = uuid.uuid4()

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    def test_qualification_review_permission_cannot_manage_panel(self, _allowed, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/titles/applications/{self.case_id}/review-rounds/",
            data=json.dumps({"roundNo": "ROUND-1", "requiredBallots": 3, "requiredPassVotes": 2}),
            content_type="application/json",
        )
        request.user = UserStub({api.REVIEW_PERMISSION})
        response = api.open_review_round(request, self.case_id)
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.PANEL_PERMISSION.encode(), response.content)

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    @patch("hr_title.api.TitlePanelService")
    def test_open_round_uses_resolved_tenant_actor_and_thresholds(self, service_cls, _allowed, _tenant):
        service_cls.return_value.open_round.return_value = SimpleNamespace(
            id=self.round_id,
            round_no="ROUND-1",
            application_case_id=self.case_id,
            attempt_no=1,
            required_ballots=3,
            required_pass_votes=2,
            status="OPEN",
        )
        request = self.factory.post(
            f"/api/v1/hr/titles/applications/{self.case_id}/review-rounds/",
            data=json.dumps({"roundNo": "ROUND-1", "requiredBallots": 3, "requiredPassVotes": 2}),
            content_type="application/json",
        )
        request.user = UserStub({api.PANEL_PERMISSION})
        response = api.open_review_round(request, self.case_id)
        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.open_round.assert_called_once_with(
            case_id=self.case_id,
            round_no="ROUND-1",
            required_ballots=3,
            required_pass_votes=2,
        )
        self.assertIn(b'"requiredPassVotes": 2', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    @patch("hr_title.api.TitlePanelService")
    def test_assignment_response_preserves_conflict_declaration(self, service_cls, _allowed, _tenant):
        service_cls.return_value.respond_assignment.return_value = SimpleNamespace(
            id=self.assignment_id,
            status="DECLINED",
            conflict_declared=True,
            conflict_note="同课题组直接合作",
        )
        request = self.factory.post(
            f"/api/v1/hr/titles/review-assignments/{self.assignment_id}/respond/",
            data=json.dumps({"accept": True, "conflictDeclared": True, "conflictNote": "同课题组直接合作"}),
            content_type="application/json",
        )
        request.user = UserStub({api.PANEL_PERMISSION})
        response = api.respond_review_assignment(request, self.assignment_id)
        self.assertEqual(response.status_code, 200)
        service_cls.return_value.respond_assignment.assert_called_once_with(
            self.assignment_id,
            accept=True,
            conflict_declared=True,
            conflict_note="同课题组直接合作",
        )
        self.assertIn(b'"conflictDeclared": true', response.content)

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    @patch("hr_title.api.TitlePanelService")
    def test_submit_ballot_preserves_recommendation_score_and_rationale(self, service_cls, _allowed, _tenant):
        service_cls.return_value.submit_ballot.return_value = SimpleNamespace(
            id=uuid.uuid4(),
            ballot_no="BAL-1",
            review_round_id=self.round_id,
            assignment_id=self.assignment_id,
            recommendation="PASS",
            score="91.50",
        )
        request = self.factory.post(
            f"/api/v1/hr/titles/review-assignments/{self.assignment_id}/ballots/",
            data=json.dumps({"ballotNo": "BAL-1", "recommendation": "PASS", "score": "91.50", "rationale": "达到要求"}),
            content_type="application/json",
        )
        request.user = UserStub({api.PANEL_PERMISSION})
        response = api.submit_review_ballot(request, self.assignment_id)
        self.assertEqual(response.status_code, 201)
        service_cls.return_value.submit_ballot.assert_called_once_with(
            assignment_id=self.assignment_id,
            ballot_no="BAL-1",
            recommendation="PASS",
            score="91.50",
            rationale="达到要求",
        )
        self.assertIn(b'"recommendation": "PASS"', response.content)

    @patch("hr_title.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_title.api.get_allowed_company_ids", return_value={7})
    @patch("hr_title.api.TitlePanelService")
    def test_quorum_conflict_maps_to_409(self, service_cls, _allowed, _tenant):
        service_cls.return_value.close_round.side_effect = TitlePanelError(
            "TITLE_REVIEW_QUORUM_NOT_MET", "requires 3 ballots, got 2"
        )
        request = self.factory.post(f"/api/v1/hr/titles/review-rounds/{self.round_id}/close/")
        request.user = UserStub({api.PANEL_PERMISSION})
        response = api.close_review_round(request, self.round_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"TITLE_REVIEW_QUORUM_NOT_MET", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get(f"/api/v1/hr/titles/review-rounds/{self.round_id}/close/")
        request.user = UserStub({api.PANEL_PERMISSION})
        response = api.close_review_round(request, self.round_id)
        self.assertEqual(response.status_code, 405)
