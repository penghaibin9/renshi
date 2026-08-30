"""Regression suite for the six formerly shadowed HR04 collection routes."""

from collections import Counter
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden, JsonResponse
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import resolve

from hr_recruitment.api import collection
from hr_recruitment.api.urls import urlpatterns
from hr_recruitment.services.campaign_service import CampaignServiceError
from hr_recruitment.services.candidate_service import CandidateServiceError


COLLECTION_CASES = (
    (
        "/api/v1/hr/recruitment/proposed-hires",
        collection.proposed_hire_collection,
        "hr_recruitment.api.proposed_hire.proposed_hire_list",
        "hr_recruitment.api.proposed_hire.create_proposed_hire",
    ),
    (
        "/api/v1/hr/recruitment/applications/00000000-0000-0000-0000-000000000001/medical",
        collection.medical_collection,
        "hr_recruitment.api.medical_background.medical_summary",
        "hr_recruitment.api.medical_background.record_medical",
    ),
    (
        "/api/v1/hr/recruitment/applications/00000000-0000-0000-0000-000000000001/background",
        collection.background_collection,
        "hr_recruitment.api.medical_background.background_summary",
        "hr_recruitment.api.medical_background.record_background",
    ),
    (
        "/api/v1/hr/recruitment/candidates",
        collection.candidate_collection,
        "hr_recruitment.api.candidate.list_candidates",
        "hr_recruitment.api.candidate.create_candidate",
    ),
    (
        "/api/v1/hr/recruitment/campaigns",
        collection.campaign_collection,
        "hr_recruitment.api.campaign.list_campaigns",
        "hr_recruitment.api.campaign.create_campaign",
    ),
    (
        "/api/v1/hr/recruitment/plans",
        collection.plan_collection,
        "hr_recruitment.api.plan.list_plans",
        "hr_recruitment.api.plan.create_plan",
    ),
)

MINIMAL_MIDDLEWARE = (
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
)


def csrf_failure(_request, reason=""):
    return HttpResponseForbidden(f"CSRF_FAILED:{reason}")


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    MIDDLEWARE=MINIMAL_MIDDLEWARE,
    CSRF_FAILURE_VIEW="hr_recruitment.tests.test_collection_routing_p0.csrf_failure",
)
class Hr04CollectionResolverTests(SimpleTestCase):
    def test_module_has_no_duplicate_concrete_routes(self):
        routes = [pattern.pattern._route for pattern in urlpatterns]
        duplicates = {route: count for route, count in Counter(routes).items() if count > 1}
        self.assertEqual(duplicates, {})

    def test_each_canonical_collection_resolves_to_one_method_adapter(self):
        for path, expected, _get_target, _post_target in COLLECTION_CASES:
            with self.subTest(path=path):
                self.assertIs(resolve(path).func, expected)

    def test_client_dispatches_get_and_post_for_all_six_collections(self):
        client = Client()
        for path, _expected, get_target, post_target in COLLECTION_CASES:
            with self.subTest(path=path, method="GET"), patch(
                get_target,
                return_value=JsonResponse({"handler": "GET"}),
            ) as get_handler:
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"handler": "GET"})
                get_handler.assert_called_once()

            with self.subTest(path=path, method="POST"), patch(
                post_target,
                return_value=JsonResponse({"handler": "POST"}),
            ) as post_handler:
                response = client.post(path, data="{}", content_type="application/json")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"handler": "POST"})
                post_handler.assert_called_once()

    def test_unsupported_method_returns_405_from_single_callback(self):
        response = Client().put(
            "/api/v1/hr/recruitment/candidates",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)

    def test_post_is_csrf_protected(self):
        response = Client(enforce_csrf_checks=True).post(
            "/api/v1/hr/recruitment/candidates",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_legacy_root_redirects_get_and_post_to_same_canonical_writer(self):
        client = Client()
        legacy = "/api/hr/v1/recruitment/candidates?source=legacy"
        expected = "/api/v1/hr/recruitment/candidates?source=legacy"
        response = client.get(legacy)
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], expected)
        response = client.post(legacy, data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], expected)


@override_settings(ALLOWED_HOSTS=["testserver"], MIDDLEWARE=MINIMAL_MIDDLEWARE)
class Hr04CollectionSecurityAndErrorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.superuser = user_model.objects.create_user(
            username="hr04_collection_superuser",
            email="hr04_collection_superuser@example.test",
            password="test-only-password",
            is_staff=True,
            is_superuser=True,
        )
        cls.no_perm_user = user_model.objects.create_user(
            username="hr04_collection_no_perm",
            email="hr04_collection_no_perm@example.test",
            password="test-only-password",
        )

    def _client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    @patch("hr_recruitment.api.candidate.candidate_selector.list_candidates")
    def test_authenticated_tenant_get_reaches_list_handler(self, list_candidates, _tenant):
        list_candidates.return_value = {"items": [], "total": 0}
        response = self._client_for(self.superuser).get(
            "/api/v1/hr/recruitment/candidates"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 0)
        list_candidates.assert_called_once()
        self.assertEqual(list_candidates.call_args.kwargs["tenant_id"], 41004)

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    @patch("hr_recruitment.api.candidate.CandidateService.create_candidate")
    def test_authenticated_tenant_post_reaches_create_handler(self, create, _tenant):
        candidate_id = uuid4()
        create.return_value = SimpleNamespace(id=candidate_id, candidate_uid="c-route-p0")
        response = self._client_for(self.superuser).post(
            "/api/v1/hr/recruitment/candidates",
            data=json.dumps({"legal_name": "测试候选人"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["id"], str(candidate_id))
        create.assert_called_once()

    def test_missing_tenant_fails_closed(self):
        response = self._client_for(self.superuser).get(
            "/api/v1/hr/recruitment/candidates"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "TENANT_CONTEXT_REQUIRED")

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    def test_missing_permission_fails_closed(self, _tenant):
        response = self._client_for(self.no_perm_user).get(
            "/api/v1/hr/recruitment/candidates"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PERMISSION_DENIED")

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    def test_invalid_json_returns_400_envelope(self, _tenant):
        response = self._client_for(self.superuser).post(
            "/api/v1/hr/recruitment/candidates",
            data="{not-json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_JSON")
        self.assertTrue(response.json()["requestId"])

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    @patch("hr_recruitment.api.campaign.CampaignService.create_campaign")
    def test_conflict_returns_409_envelope(self, create_campaign, _tenant):
        create_campaign.side_effect = CampaignServiceError(
            "CAMPAIGN_CONFLICT", "招聘项目冲突", http_status=409
        )
        response = self._client_for(self.superuser).post(
            "/api/v1/hr/recruitment/campaigns",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "CAMPAIGN_CONFLICT")

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    @patch("hr_recruitment.api.candidate.CandidateService.create_candidate")
    def test_validation_returns_422_envelope(self, create_candidate, _tenant):
        create_candidate.side_effect = CandidateServiceError(
            "CANDIDATE_INVALID", "候选人资料无效", http_status=422
        )
        response = self._client_for(self.superuser).post(
            "/api/v1/hr/recruitment/candidates",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "CANDIDATE_INVALID")

    @patch("hr_recruitment.api.base.resolve_tenant_from_request", return_value=41004)
    @patch("hr_recruitment.api.candidate.candidate_selector.get_candidate", return_value=None)
    def test_wrong_tenant_shape_is_not_enumerable(self, _get_candidate, _tenant):
        candidate_id = UUID("00000000-0000-0000-0000-000000000001")
        response = self._client_for(self.superuser).get(
            f"/api/v1/hr/recruitment/candidates/{candidate_id}"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "CANDIDATE_NOT_FOUND")
