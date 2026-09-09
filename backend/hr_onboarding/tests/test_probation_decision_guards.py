"""HR05 probation decision guards; run with the repository MySQL test settings."""

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase

from hr_onboarding.api.probations import probation_confirm, probation_extend, probation_fail
from hr_onboarding.constants import ProbationResult, ProbationStatus
from hr_onboarding.models import HrProbationCase, HrProbationExtension


class ProbationDecisionGuardTests(TestCase):
    def setUp(self):
        self.tenant = 90510
        self.factory = RequestFactory()
        self.record = HrProbationCase.objects.create(
            tenant_id=self.tenant,
            staff_master_id=uuid4(),
            employment_relationship_id=uuid4(),
            start_date=date(2026, 1, 1),
            planned_end_date=date(2026, 7, 1),
            status=ProbationStatus.IN_PROGRESS,
        )

    def _request(self, path, payload, *, permissions=None, version=None):
        allowed = {"hr05.probation.finalize"} if permissions is None else set(permissions)
        extra = {}
        if version is not None:
            extra["HTTP_IF_MATCH"] = str(version)
        request = self.factory.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
        )
        request.user = SimpleNamespace(
            id=90510,
            is_authenticated=True,
            is_superuser=False,
            has_perm=lambda code: code in allowed,
        )
        return request

    def _call(self, view, payload, *, permissions=None, version=None):
        request = self._request("/probation-action", payload, permissions=permissions, version=version)
        with patch("hr_onboarding.api.base.resolve_tenant_from_request", return_value=self.tenant), patch(
            "base.auth_backends.get_allowed_company_ids", return_value={self.tenant}
        ), patch("hr_onboarding.api.base.get_authority_mode", return_value="HR05_AUTHORITY"):
            return view(request, self.record.id)

    def test_stale_version_rejected_without_mutation(self):
        response = self._call(
            probation_confirm,
            {"reason": "考核通过"},
            version=self.record.version + 1,
        )
        self.assertEqual(response.status_code, 409)
        body = json.loads(response.content)
        self.assertEqual(body["error"]["code"], "VERSION_CONFLICT")
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ProbationStatus.IN_PROGRESS)
        self.assertEqual(self.record.result, ProbationResult.NONE)

    def test_confirm_requires_reason_and_accepts_json_with_current_version(self):
        response = self._call(probation_confirm, {"reason": ""}, version=self.record.version)
        self.assertEqual(response.status_code, 400)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ProbationStatus.IN_PROGRESS)

        response = self._call(
            probation_confirm,
            {"reason": "单位评价、人事审核完成，同意转正"},
            version=self.record.version,
        )
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)["data"]
        self.assertEqual(body["status"], ProbationStatus.CONFIRMED)
        self.assertEqual(body["result"], ProbationResult.CONFIRMED)
        self.assertEqual(body["version"], 2)

    def test_extend_requires_reason_and_preserves_history(self):
        response = self._call(
            probation_extend,
            {"new_end_date": "2026-08-01", "reason": "继续观察教学适应情况"},
            version=self.record.version,
        )
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.planned_end_date, date(2026, 8, 1))
        self.assertEqual(self.record.extension_count, 1)
        extension = HrProbationExtension.objects.get(probation_case=self.record)
        self.assertEqual(extension.old_end_date, date(2026, 7, 1))
        self.assertEqual(extension.new_end_date, date(2026, 8, 1))
        self.assertEqual(extension.reason, "继续观察教学适应情况")

    def test_fail_requires_reason(self):
        response = self._call(probation_fail, {"reason": ""}, version=self.record.version)
        self.assertEqual(response.status_code, 400)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ProbationStatus.IN_PROGRESS)

    def test_finalize_permission_still_fails_closed_before_write(self):
        request = self._request(
            "/probation-action",
            {"reason": "无权限用户不得生效"},
            permissions={"hr05.probation.manage"},
            version=self.record.version,
        )
        with self.assertRaises(PermissionDenied):
            probation_confirm(request, self.record.id)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ProbationStatus.IN_PROGRESS)
