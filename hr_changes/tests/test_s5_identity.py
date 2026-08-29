"""S5 岗位与身份变更契约测试。"""

import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from hr_changes.api import identity_changes as identity_api
from hr_changes.constants import ChangeActionCode
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.identity_change_service import IdentityChangeService
from hr_changes.tests.factories import make_action, make_org, make_person, make_reason, make_staff
from hr_staff.services.employment_service import EmploymentService

TENANT = 1


def ctx():
    return HrChangeRequestContext(
        tenant_id=TENANT, scope=HrChangeScope(scope_type="SCHOOL")
    )


class IdentityChangeServiceTests(TestCase):
    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T6001")
        self.rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            employment_type="FULL_TIME",
            effective_from=date(2024, 9, 1),
        )

    def _create(self, action_code, proposals, **kwargs):
        action = make_action(TENANT, action_code)
        reason = make_reason(TENANT, action_code)
        return IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
            staff_master_id=self.staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date(2026, 9, 1),
            proposals=proposals,
            **kwargs,
        )

    def test_post_category_change(self):
        case = self._create(
            ChangeActionCode.POST_CATEGORY_CHANGE,
            [
                {
                    "domain": "assignment",
                    "field_code": "post_catalog",
                    "proposed_value_display": "管理岗",
                }
            ],
        )
        self.assertEqual(case.status, "DRAFT")
        self.assertEqual(case.proposals.first().field_code, "post_catalog")

    def test_employee_category_change(self):
        case = self._create(
            ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
            [
                {
                    "domain": "staff",
                    "field_code": "staff_category_code",
                    "proposed_value_ref": "ADMIN",
                    "proposed_value_display": "行政管理",
                }
            ],
        )
        self.assertEqual(case.action_id.code, ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE)

    def test_employee_category_rejects_display_only_or_unknown_code(self):
        for value in (None, "NOT_A_CATEGORY"):
            with self.subTest(value=value):
                with self.assertRaises(ChangeServiceError) as caught:
                    self._create(
                        ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
                        [
                            {
                                "domain": "staff",
                                "field_code": "staff_category_code",
                                "proposed_value_ref": value,
                                "proposed_value_display": "任意展示值",
                            }
                        ],
                    )
                self.assertEqual(caught.exception.code, "CHANGE_INVALID_PAYLOAD")

    def test_disallowed_field_rejected(self):
        with self.assertRaises(ChangeServiceError) as caught:
            self._create(
                ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
                [
                    {
                        "domain": "assignment",
                        "field_code": "position",
                        "proposed_value_display": "P1",
                    }
                ],
            )
        self.assertEqual(caught.exception.code, "CHANGE_INVALID_PAYLOAD")

    def test_add_secondary_requires_org_position(self):
        org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        with self.assertRaises(ChangeServiceError) as caught:
            self._create(
                ChangeActionCode.ADD_SECONDARY_ASSIGNMENT,
                [
                    {
                        "domain": "assignment",
                        "field_code": "organization",
                        "proposed_value_ref": str(org.id),
                    }
                ],
            )
        self.assertEqual(caught.exception.code, "CHANGE_INVALID_PAYLOAD")

    def test_employment_type_hr07_policy_warning(self):
        action = make_action(TENANT, ChangeActionCode.EMPLOYMENT_TYPE_CHANGE)
        action.followup_policy_json = {
            "employment_type_policy": "REQUIRE_HR07_CONTRACT"
        }
        action.save()
        case = self._create(
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
            [
                {
                    "domain": "relationship",
                    "field_code": "relationship_type",
                    "proposed_value_ref": "CONTRACT",
                    "proposed_value_display": "合同制",
                }
            ],
        )
        result = IdentityChangeService(TENANT).validate_identity_change(case)
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("CONTRACT_REVIEW_REQUIRED", codes)

    def test_employment_type_rejects_unknown_controlled_codes(self):
        with self.assertRaises(ChangeServiceError) as caught:
            self._create(
                ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
                [
                    {
                        "domain": "relationship",
                        "field_code": "relationship_type",
                        "proposed_value_ref": "UNKNOWN_REL",
                        "proposed_value_display": "未知",
                    }
                ],
            )
        self.assertEqual(caught.exception.code, "CHANGE_INVALID_PAYLOAD")

    def test_change_matrix(self):
        case = self._create(
            ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
            [
                {
                    "domain": "staff",
                    "field_code": "staff_category_code",
                    "proposed_value_ref": "ADMIN",
                    "proposed_value_display": "行政管理",
                }
            ],
        )
        matrix = IdentityChangeService(TENANT).change_matrix(case)
        dimensions = {item["dimension"]: item for item in matrix}
        self.assertEqual(dimensions["人员类别"]["after"], "行政管理")
        self.assertTrue(dimensions["人员类别"]["affectsDownstream"])
        self.assertFalse(dimensions["岗位类别"]["affectsDownstream"])

    def test_validate_required_fields(self):
        case = self._create(
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
            [
                {
                    "domain": "relationship",
                    "field_code": "employment_type",
                    "proposed_value_ref": "FULL_TIME",
                    "proposed_value_display": "全职",
                }
            ],
        )
        result = IdentityChangeService(TENANT).validate_identity_change(case)
        self.assertTrue(
            any(
                blocker["code"] == "CHANGE_INVALID_PAYLOAD"
                for blocker in result["blockers"]
            )
        )


class IdentityApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username="hr06id", password="x", is_superuser=True
        )
        self.staff = make_staff(TENANT, make_person(TENANT, "李某某"), "T6002")
        self.action = make_action(TENANT, ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE)
        self.reason = make_reason(TENANT, ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE)

    def _req(self, method, path, body=None):
        if body is not None:
            request = getattr(self.factory, method)(
                path, data=json.dumps(body), content_type="application/json"
            )
        else:
            request = getattr(self.factory, method)(path)
        request.user = self.user
        return request

    def test_create_identity_api(self):
        body = {
            "staffMasterId": str(self.staff.id),
            "actionId": str(self.action.id),
            "reasonId": str(self.reason.id),
            "requestedEffectiveAt": "2026-09-01",
            "proposals": [
                {
                    "domain": "staff",
                    "field_code": "staff_category_code",
                    "proposed_value_ref": "ADMIN",
                    "proposed_value_display": "行政管理",
                }
            ],
        }
        with mock.patch(
            "hr_changes.api.identity_changes.make_hr_change_context",
            return_value=ctx(),
        ):
            response = identity_api.identity_change_create(
                self._req("post", "/api/hr/v1/changes/identity-changes", body)
            )
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)["data"]
        self.assertEqual(data["actionLabel"], "人员类别变更")
        self.assertIn("changeMatrix", data)
        self.assertIn("validation", data)

    def test_identity_list_api(self):
        from hr_changes.tests.factories import make_case

        make_case(TENANT, ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE)
        with mock.patch(
            "hr_changes.api.identity_changes.make_hr_change_context",
            return_value=ctx(),
        ):
            response = identity_api.identity_change_list(
                self._req("get", "/api/hr/v1/changes/identity-changes")
            )
        body = json.loads(response.content)
        self.assertEqual(body["data"]["total"], 1)
        self.assertEqual(body["data"]["items"][0]["statusLabel"], "草稿")
