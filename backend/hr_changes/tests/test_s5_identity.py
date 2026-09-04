"""S5 岗位与身份变更契约测试。"""

import json
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from hr_changes.api import identity_changes as identity_api
from hr_changes.constants import ChangeActionCode
from hr_changes.context import HrChangeRequestContext, HrChangeScope
from hr_changes.services.change_service import ChangeServiceError
from hr_changes.services.identity_change_service import IdentityChangeService
from hr_changes.tests.factories import (
    make_action,
    make_catalog_version,
    make_org,
    make_person,
    make_position,
    make_reason,
    make_staff,
)
from hr_staff.services.employment_service import EmploymentService

TENANT = 1
EFFECTIVE_DATE = timezone.localdate() + timedelta(days=30)


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
            requested_effective_at=EFFECTIVE_DATE,
            proposals=proposals,
            **kwargs,
        )

    def test_post_category_change(self):
        catalog_version = make_catalog_version(TENANT, "管理岗")
        catalog_version.status = "ACTIVE"
        catalog_version.save(update_fields=["status"])
        case = self._create(
            ChangeActionCode.POST_CATEGORY_CHANGE,
            [
                {
                    "domain": "assignment",
                    "field_code": "post_catalog",
                    "proposed_value_ref": str(catalog_version.id),
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

    def test_add_secondary_rejects_invalid_or_excess_total_fte(self):
        from decimal import Decimal

        from hr_staff.constants import AssignmentType
        from hr_staff.services.assignment_service import AssignmentService

        source_org = make_org(TENANT, "FTE-SOURCE", "主岗学院", date(2020, 1, 1))
        target_org = make_org(TENANT, "FTE-TARGET", "兼岗学院", date(2020, 1, 1))
        source_position = make_position(TENANT, source_org, "FTE-SOURCE-P", max_incumbents=1)
        target_position = make_position(TENANT, target_org, "FTE-TARGET-P", max_incumbents=1)
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=self.rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=source_org,
            position_id=source_position,
            fte=Decimal("1.00"),
            source_business_type="MIGRATION_VERIFIED",
        )
        for value in (None, "not-a-number", "0", "0.51"):
            with self.subTest(value=value):
                proposals = [
                    {"domain": "assignment", "field_code": "organization", "proposed_value_ref": str(target_org.id)},
                    {"domain": "assignment", "field_code": "position", "proposed_value_ref": str(target_position.id)},
                ]
                if value is not None:
                    proposals.append({"domain": "assignment", "field_code": "fte", "proposed_value_ref": value})
                with self.assertRaises(ChangeServiceError) as caught:
                    self._create(ChangeActionCode.ADD_SECONDARY_ASSIGNMENT, proposals)
                self.assertEqual(caught.exception.code, "CHANGE_INVALID_PAYLOAD")

    def test_assignment_target_position_must_belong_to_selected_org(self):
        target_org = make_org(TENANT, "ORG-MATCH", "目标学院", date(2020, 1, 1))
        other_org = make_org(TENANT, "ORG-OTHER", "其他学院", date(2020, 1, 1))
        position = make_position(TENANT, other_org, "OTHER-POSITION", max_incumbents=1)
        with self.assertRaises(ChangeServiceError) as caught:
            self._create(
                ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
                [
                    {"domain": "assignment", "field_code": "organization", "proposed_value_ref": str(target_org.id)},
                    {"domain": "assignment", "field_code": "position", "proposed_value_ref": str(position.id)},
                ],
            )
        self.assertEqual(caught.exception.code, "CHANGE_TARGET_POSITION_INVALID")

    def test_manager_change_requires_other_staff_in_same_tenant(self):
        action_code = ChangeActionCode.MANAGER_CHANGE
        manager = make_staff(TENANT, make_person(TENANT, "真实主管"), "T6002")
        case = self._create(
            action_code,
            [{"domain": "assignment", "field_code": "reporting_staff", "proposed_value_ref": str(manager.id)}],
        )
        proposal = case.proposals.get(field_code="reporting_staff")
        self.assertEqual(proposal.proposed_value_ref, str(manager.id))
        self.assertEqual(proposal.proposed_value_display, "真实主管")
        for invalid in (self.staff.id, make_staff(2, make_person(2, "跨校主管"), "OTHER-MANAGER").id):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ChangeServiceError) as caught:
                    self._create(
                        action_code,
                        [{"domain": "assignment", "field_code": "reporting_staff", "proposed_value_ref": str(invalid)}],
                    )
                self.assertEqual(caught.exception.code, "CHANGE_INVALID_PAYLOAD")

    def test_primary_switch_sets_canonical_refs_and_requires_position_gate(self):
        from hr_changes.integrations.hr02 import PositionGate

        org = make_org(TENANT, "RGXY-PRIMARY", "人工智能学院", date(2020, 1, 1))
        position = make_position(TENANT, org, "AI-PRIMARY-P01", max_incumbents=1)
        case = self._create(
            ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
            [
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "proposed_value_ref": str(org.id),
                },
                {
                    "domain": "assignment",
                    "field_code": "position",
                    "proposed_value_ref": str(position.id),
                },
            ],
        )

        self.assertEqual(case.target_org_id_id, org.id)
        self.assertEqual(case.target_position_id_id, position.id)
        gate = PositionGate(TENANT)
        self.assertTrue(gate.needs_position(ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH))
        reservation = gate.reserve_for_case(case)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.position_id_id, position.id)

    def test_primary_switch_rejects_cross_tenant_canonical_refs(self):
        other_org = make_org(2, "OTHER", "其他学校", date(2020, 1, 1))
        other_position = make_position(2, other_org, "OTHER-P01", max_incumbents=1)
        with self.assertRaises(ChangeServiceError) as caught:
            self._create(
                ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
                [
                    {
                        "domain": "assignment",
                        "field_code": "organization",
                        "proposed_value_ref": str(other_org.id),
                    },
                    {
                        "domain": "assignment",
                        "field_code": "position",
                        "proposed_value_ref": str(other_position.id),
                    },
                ],
            )
        self.assertEqual(caught.exception.code, "CHANGE_TARGET_ORG_INVALID")

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
            "requestedEffectiveAt": EFFECTIVE_DATE.isoformat(),
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
