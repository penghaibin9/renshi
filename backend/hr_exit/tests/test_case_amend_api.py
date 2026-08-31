import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import api, case_api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr16CaseAmendApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()

    def _request(self, payload, *, permissions=()):
        request = self.factory.patch(
            f"/api/v1/hr/exit/cases/{self.case_id}/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = UserStub(permissions)
        return request

    def _case(self):
        return SimpleNamespace(
            id=self.case_id,
            case_no="EXIT-2026-001",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type="RESIGNATION",
            status="RETURNED",
            requested_date=date(2026, 8, 13),
            last_working_date=date(2026, 9, 2),
            planned_employment_end_date=date(2026, 9, 3),
            planned_access_end_at=None,
        )

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_identity_fields_are_immutable(self, _allowed, _tenant):
        request = self._request(
            {"exitType": "RETIREMENT"},
            permissions={api.MANAGE_PERMISSION},
        )

        response = case_api.amend_case(request, self.case_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"EXIT_CASE_IDENTITY_IMMUTABLE", response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.case_api.ExitCaseService")
    def test_plan_patch_uses_manage_authority_and_parsed_dates(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.update_draft.return_value = self._case()
        request = self._request(
            {
                "lastWorkingDate": "2026-09-02",
                "plannedEmploymentEndDate": "2026-09-03",
            },
            permissions={api.MANAGE_PERMISSION},
        )

        response = case_api.amend_case(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        args = service_cls.return_value.update_draft.call_args.args
        self.assertEqual(args[0], self.case_id)
        patch = args[1]
        self.assertEqual(patch.last_working_date, date(2026, 9, 2))
        self.assertEqual(patch.planned_employment_end_date, date(2026, 9, 3))
        self.assertIn(b'"schemaVersion": "hr16.exit-case.1"', response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_handover_permission_cannot_amend_case(self, _allowed, _tenant):
        request = self._request(
            {"requestedDate": "2026-08-14"},
            permissions={api.HANDOVER_PERMISSION},
        )

        response = case_api.amend_case(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(api.MANAGE_PERMISSION.encode(), response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_empty_patch_and_bad_date_are_rejected(self, _allowed, _tenant):
        empty = self._request({}, permissions={api.MANAGE_PERMISSION})
        response = case_api.amend_case(empty, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"EXIT_CASE_PATCH_EMPTY", response.content)

        bad = self._request(
            {"requestedDate": "tomorrow"},
            permissions={api.MANAGE_PERMISSION},
        )
        response = case_api.amend_case(bad, self.case_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"INVALID_FIELD", response.content)
