"""S3 API 契约测试：创建/详情/动作/envelope/中文 label 成对。"""

import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from hr_changes.api import changes as changes_api
from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.tests.factories import (
    make_action,
    make_case,
    make_effective_case,
    make_org,
    make_person,
    make_reason,
    make_staff,
)

TENANT = 1


def ctx():
    return HrChangeRequestContext(tenant_id=TENANT, scope=HrChangeScope(scope_type="SCHOOL"))


class ChangeApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="hr06api", password="x", is_superuser=True
        )
        self.action = make_action(TENANT)
        self.reason = make_reason(TENANT, ChangeActionCode.ORG_TRANSFER)
        self.org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T8001")

    def _req(self, method, path, body=None):
        if body is not None:
            request = getattr(self.factory, method)(path, data=json.dumps(body), content_type="application/json")
        else:
            request = getattr(self.factory, method)(path)
        request.user = self.user
        return request

    def _body(self, resp):
        return json.loads(resp.content)

    def test_create_case_api(self):
        body = {
            "staffMasterId": str(self.staff.id),
            "actionId": str(self.action.id),
            "reasonId": str(self.reason.id),
            "requestedEffectiveAt": "2026-09-01",
            "proposals": [
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "old_value_display": "计算机学院",
                    "proposed_value_display": "人工智能学院",
                }
            ],
            "targetOrgId": self.org.id,
        }
        with mock.patch("hr_changes.api.changes.make_hr_change_context", return_value=ctx()):
            resp = changes_api.change_list(self._req("post", "/api/hr/v1/changes", body))
        self.assertEqual(resp.status_code, 201)
        data = self._body(resp)["data"]
        self.assertEqual(data["actionCode"], "ORG_TRANSFER")
        self.assertEqual(data["actionLabel"], "组织调动")
        self.assertEqual(data["status"], "DRAFT")
        self.assertEqual(data["statusLabel"], "草稿")

    def test_detail_and_actions_api(self):
        case = make_case(TENANT, status=CaseStatus.READY_TO_SUBMIT)
        with mock.patch("hr_changes.api.changes.make_hr_change_context", return_value=ctx()):
            detail = changes_api.change_detail(self._req("get", f"/api/hr/v1/changes/{case.id}"), case.id)
            self.assertEqual(self._body(detail)["data"]["caseNo"], case.case_no)

            submit = changes_api.change_action(
                self._req("post", f"/api/hr/v1/changes/{case.id}/submit", {"requestId": "req-1"}),
                case.id,
                "submit",
            )
            self.assertEqual(self._body(submit)["data"]["status"], "SUBMITTED")

            start = changes_api.change_action(
                self._req("post", f"/api/hr/v1/changes/{case.id}/start-approval", {}), case.id, "start-approval"
            )
            self.assertEqual(self._body(start)["data"]["status"], "UNDER_APPROVAL")

    def test_version_conflict_api(self):
        case = make_case(TENANT, status=CaseStatus.READY_TO_SUBMIT)
        with mock.patch("hr_changes.api.changes.make_hr_change_context", return_value=ctx()):
            resp = changes_api.change_action(
                self._req("post", f"/api/hr/v1/changes/{case.id}/submit?version=99", {}), case.id, "submit"
            )
        body = self._body(resp)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(body["error"]["code"], "VERSION_CONFLICT")

    def test_validate_api(self):
        case = make_case(TENANT)
        with mock.patch("hr_changes.api.changes.make_hr_change_context", return_value=ctx()):
            resp = changes_api.change_validate(self._req("post", f"/api/hr/v1/changes/{case.id}/validate"), case.id)
        body = self._body(resp)
        codes = {b["code"] for b in body["data"]["blockers"]}
        self.assertIn("CHANGE_INVALID_PAYLOAD", codes)  # 缺少必填 proposal 字段

    def test_future_api(self):
        case = make_case(TENANT, status=CaseStatus.APPROVED_WAITING_EFFECTIVE)
        with mock.patch("hr_changes.api.changes.make_hr_change_context", return_value=ctx()):
            resp = changes_api.future_changes(self._req("get", "/api/hr/v1/changes/future"))
        body = self._body(resp)
        self.assertEqual(body["data"]["total"], 1)
        self.assertEqual(body["data"]["items"][0]["caseNo"], case.case_no)

    def test_machine_field_names_no_chinese(self):
        case = make_effective_case(TENANT)
        with mock.patch("hr_changes.api.changes.make_hr_change_context", return_value=ctx()):
            resp = changes_api.change_detail(self._req("get", f"/api/hr/v1/changes/{case.id}"), case.id)
        data = self._body(resp)["data"]
        for key in data:
            self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in key), f"机器字段名含中文: {key}")
        self.assertEqual(data["statusLabel"], "已生效")
