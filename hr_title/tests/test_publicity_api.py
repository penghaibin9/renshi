import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpRequest
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from hr_title import publicity_api
from hr_title.api import HrTitleAccessError
from hr_title.services.publicity_service import TitlePublicityError


class Hr13PublicityApiContractTests(SimpleTestCase):
    def _request(self, body=None):
        request = HttpRequest()
        request.method = "POST"
        request.body = json.dumps(body or {}).encode("utf-8")
        request.user = SimpleNamespace(id=9, is_authenticated=True, is_superuser=False)
        return request

    def test_publicity_routes_are_canonical(self):
        case_id = uuid.uuid4()
        publicity_id = uuid.uuid4()
        appeal_id = uuid.uuid4()
        expected = {
            "hr_title_api:publicity-open": (
                {"case_id": case_id},
                f"/api/v1/hr/titles/applications/{case_id}/publicities/",
            ),
            "hr_title_api:appeal-lodge": (
                {"publicity_id": publicity_id},
                f"/api/v1/hr/titles/publicities/{publicity_id}/appeals/",
            ),
            "hr_title_api:appeal-resolve": (
                {"appeal_id": appeal_id},
                f"/api/v1/hr/titles/appeals/{appeal_id}/resolve/",
            ),
            "hr_title_api:publicity-close": (
                {"publicity_id": publicity_id},
                f"/api/v1/hr/titles/publicities/{publicity_id}/close/",
            ),
            "hr_title_api:publicity-cancel": (
                {"publicity_id": publicity_id},
                f"/api/v1/hr/titles/publicities/{publicity_id}/cancel/",
            ),
        }
        for name, (kwargs, path) in expected.items():
            self.assertEqual(reverse(name, kwargs=kwargs), path)
            self.assertEqual(resolve(path).view_name, name)

    @patch("hr_title.publicity_api.resolve_request_tenant")
    def test_publicity_write_requires_dedicated_permission(self, resolve_tenant):
        request = self._request()
        resolve_tenant.side_effect = HrTitleAccessError(
            "PERMISSION_DENIED", "missing publicity permission"
        )
        response = publicity_api.close_publicity(request, uuid.uuid4())
        self.assertEqual(response.status_code, 403)
        resolve_tenant.assert_called_once_with(
            request,
            required_permission="hr.title.publicity",
        )

    @patch("hr_title.publicity_api.TitlePublicityService")
    @patch("hr_title.publicity_api.resolve_request_tenant", return_value=77)
    def test_open_publicity_parses_iso_datetimes_and_returns_201(
        self, resolve_tenant, service_cls
    ):
        case_id = uuid.uuid4()
        record = SimpleNamespace(
            id=uuid.uuid4(),
            publicity_no="PUB-001",
            application_case_id=case_id,
            start_at=publicity_api._dt("2026-08-13T09:00:00+08:00", "startAt"),
            end_at=publicity_api._dt("2026-08-18T09:00:00+08:00", "endAt"),
            status="OPEN",
            content_snapshot_json={"title": "副教授拟通过"},
        )
        service_cls.return_value.open_publicity.return_value = record
        response = publicity_api.open_publicity(
            self._request(
                {
                    "publicityNo": "PUB-001",
                    "startAt": "2026-08-13T09:00:00+08:00",
                    "endAt": "2026-08-18T09:00:00+08:00",
                    "contentSnapshot": {"title": "副教授拟通过"},
                }
            ),
            case_id,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        service_cls.return_value.open_publicity.assert_called_once()
        kwargs = service_cls.return_value.open_publicity.call_args.kwargs
        self.assertEqual(kwargs["case_id"], case_id)
        self.assertEqual(kwargs["publicity_no"], "PUB-001")
        self.assertEqual(kwargs["content_snapshot"], {"title": "副教授拟通过"})

    @patch("hr_title.publicity_api.TitlePublicityService")
    @patch("hr_title.publicity_api.resolve_request_tenant", return_value=77)
    def test_outside_window_conflict_maps_to_409(self, resolve_tenant, service_cls):
        service_cls.return_value.lodge_appeal.side_effect = TitlePublicityError(
            "TITLE_APPEAL_OUTSIDE_WINDOW",
            "appeal must be lodged within the publicity window",
        )
        response = publicity_api.lodge_appeal(
            self._request({"appealNo": "APL-1", "reason": "程序异议"}),
            uuid.uuid4(),
        )
        self.assertEqual(response.status_code, 409)

    def test_non_post_is_rejected(self):
        request = self._request()
        request.method = "GET"
        response = publicity_api.cancel_publicity(request, uuid.uuid4())
        self.assertEqual(response.status_code, 405)
