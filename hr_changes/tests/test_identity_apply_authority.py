"""HR06 identity actions that are exposed in V2 must prove real HR03 Authority effects."""

from datetime import date

from django.test import TestCase

from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.services.apply_service import ApplyService
from hr_changes.services.change_service import ChangeService
from hr_changes.services.identity_change_service import IdentityChangeService
from hr_changes.tests.factories import make_action, make_person, make_reason, make_staff
from hr_staff.services.employment_service import EmploymentService

TENANT = 1


class IdentityApplyAuthorityTests(TestCase):
    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "身份生效测试教师"), "T-ID-APPLY-1")
        self.relationship = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            employment_type="FULL_TIME",
            effective_from=date(2024, 9, 1),
        )

    def _apply(self, case):
        workflow = ChangeService(TENANT, actor_user_id=1)
        case = workflow.submit(case.id)
        case = workflow.start_approval(case.id)
        case = workflow.approve_all(case.id)
        self.assertEqual(case.status, CaseStatus.APPROVED_WAITING_EFFECTIVE)
        applied = ApplyService(TENANT, actor_user_id=1).apply_case(case.id)
        self.assertEqual(applied.status, CaseStatus.EFFECTIVE)
        return applied

    def test_employee_category_change_reaches_hr03_authority(self):
        action = make_action(TENANT, ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE)
        reason = make_reason(TENANT, ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE)
        case = IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
            staff_master_id=self.staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[
                {
                    "domain": "staff",
                    "field_code": "staff_category_code",
                    "proposed_value_ref": "ADMIN",
                    "proposed_value_display": "行政管理",
                }
            ],
        )
        self._apply(case)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.staff_category_code, "ADMIN")

    def test_employment_type_change_reaches_hr03_relationship_authority(self):
        action = make_action(TENANT, ChangeActionCode.EMPLOYMENT_TYPE_CHANGE)
        reason = make_reason(TENANT, ChangeActionCode.EMPLOYMENT_TYPE_CHANGE)
        case = IdentityChangeService(TENANT, actor_user_id=1).create_identity_change(
            staff_master_id=self.staff,
            action_id=action,
            reason_id=reason,
            requested_effective_at=date.today(),
            proposals=[
                {
                    "domain": "relationship",
                    "field_code": "relationship_type",
                    "proposed_value_ref": "CONTRACT",
                    "proposed_value_display": "合同制",
                },
                {
                    "domain": "relationship",
                    "field_code": "employment_type",
                    "proposed_value_ref": "PART_TIME",
                    "proposed_value_display": "兼职",
                },
            ],
        )
        self._apply(case)
        self.relationship.refresh_from_db()
        self.assertEqual(self.relationship.relationship_type, "CONTRACT")
        self.assertEqual(self.relationship.employment_type, "PART_TIME")
