import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_title import result_api
from hr_title.services.result_service import TitleResultError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class FormalTitleResultApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()
        self.result_id = uuid.uuid4()
        self.person_id = uuid.uuid4()

    def _result(self, *, result_id=None, status="EFFECTIVE", supersedes=None):
        return SimpleNamespace(
            id=result_id or self.result_id,
            result_no="RESULT-2026-001",
            person_id=self.person_id,
            application_case_id=self.case_id,
            title_code="PRO-ASSOCIATE",
            title_name="副教授",
            title_series_code="PROFESSIONAL",
            title_level_code="L7",
            effective_from=date(2026, 9, 1),
            effective_to=None,
            status=status,
            supersedes_result_id=supersedes,
        )

    @patch("hr_title.result_api.ProfessionalTitleResultService")
    @patch("hr_title.result_api.resolve_request_tenant", return_value=77)
    def test_make_effective_uses_dedicated_result_permission_and_typed_payload(
        self, tenant_resolver, service_cls
    ):
        service_cls.return_value.make_effective.return_value = self._result()
        request = self.factory.post(
            f"/api/v1/hr/titles/applications/{self.case_id}/result/effective/",
            data=json.dumps(
                {
                    "resultNo": "RESULT-2026-001",
                    "titleCode": "PRO-ASSOCIATE",
                    "titleName": "副教授",
                    "titleSeriesCode": "PROFESSIONAL",
                    "titleLevelCode": "L7",
                    "effectiveFrom": "2026-09-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = result_api.make_effective(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=result_api.RESULT_PERMISSION
        )
        service_cls.assert_called_once_with(77, actor_user_id=88)
        kwargs = service_cls.return_value.make_effective.call_args.kwargs
        self.assertEqual(kwargs["application_case_id"], self.case_id)
        self.assertEqual(kwargs["payload"].result_no, "RESULT-2026-001")
        self.assertEqual(kwargs["payload"].effective_from, date(2026, 9, 1))
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_title.result_api.ProfessionalTitleResultService")
    @patch("hr_title.result_api.resolve_request_tenant", return_value=77)
    def test_revision_keeps_successor_payload_explicit(
        self, _tenant, service_cls
    ):
        successor_id = uuid.uuid4()
        service_cls.return_value.revise.return_value = self._result(
            result_id=successor_id,
            status="REVISED",
            supersedes=self.result_id,
        )
        request = self.factory.post(
            f"/api/v1/hr/titles/results/{self.result_id}/revisions/",
            data=json.dumps(
                {
                    "resultNo": "RESULT-REV-1",
                    "titleCode": "PRO-FULL",
                    "titleName": "教授",
                    "effectiveFrom": "2027-01-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = result_api.revise_result(request, self.result_id)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.revise.assert_called_once()
        kwargs = service_cls.return_value.revise.call_args.kwargs
        self.assertEqual(kwargs["result_id"], self.result_id)
        self.assertEqual(kwargs["payload"].title_name, "教授")
        self.assertEqual(kwargs["payload"].effective_from, date(2027, 1, 1))
        self.assertIn(b"REVISED", response.content)

    @patch("hr_title.result_api.ProfessionalTitleResultService")
    @patch("hr_title.result_api.resolve_request_tenant", return_value=77)
    def test_revoke_requires_explicit_successor_number_and_date(
        self, _tenant, service_cls
    ):
        revoked_id = uuid.uuid4()
        service_cls.return_value.revoke.return_value = self._result(
            result_id=revoked_id,
            status="REVOKED",
            supersedes=self.result_id,
        )
        request = self.factory.post(
            f"/api/v1/hr/titles/results/{self.result_id}/revoke/",
            data=json.dumps(
                {"resultNo": "RESULT-REVOKE-1", "revokedAt": "2026-10-01"}
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = result_api.revoke_result(request, self.result_id)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.revoke.assert_called_once_with(
            result_id=self.result_id,
            result_no="RESULT-REVOKE-1",
            revoked_at=date(2026, 10, 1),
        )

    @patch("hr_title.result_api.ProfessionalTitleResultService")
    @patch("hr_title.result_api.resolve_request_tenant", return_value=77)
    def test_idempotency_conflict_maps_to_409(self, _tenant, service_cls):
        service_cls.return_value.make_effective.side_effect = TitleResultError(
            "TITLE_RESULT_IDEMPOTENCY_CONFLICT",
            "result_no already belongs to a different payload",
        )
        request = self.factory.post(
            "/result/effective/",
            data=json.dumps(
                {
                    "resultNo": "RESULT-2026-001",
                    "titleCode": "PRO-FULL",
                    "titleName": "教授",
                    "effectiveFrom": "2026-09-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = result_api.make_effective(request, self.case_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"TITLE_RESULT_IDEMPOTENCY_CONFLICT", response.content)

    @patch("hr_title.result_api.resolve_request_tenant", return_value=77)
    def test_invalid_date_is_rejected_before_service(self, _tenant):
        request = self.factory.post(
            "/result/effective/",
            data=json.dumps(
                {
                    "resultNo": "R-1",
                    "titleCode": "X",
                    "titleName": "职称",
                    "effectiveFrom": "2026-99-99",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = result_api.make_effective(request, self.case_id)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_REQUEST", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get("/result/effective/")
        request.user = UserStub()
        self.assertEqual(result_api.make_effective(request, self.case_id).status_code, 405)
