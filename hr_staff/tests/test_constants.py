"""S1 · constants 契约完整性测试。"""

from django.test import SimpleTestCase

from hr_staff import constants as C


class ConstantsContractTests(SimpleTestCase):
    def test_error_codes_complete(self):
        # 总册 §27 全部错误码必须存在
        required = {
            "STAFF_NOT_FOUND",
            "STAFF_SCOPE_DENIED",
            "SENSITIVE_FIELD_DENIED",
            "TENANT_CONTEXT_REQUIRED",
            "CROSS_TENANT_REFERENCE",
            "PERSON_DUPLICATE_HARD_MATCH",
            "PERSON_DUPLICATE_REVIEW_REQUIRED",
            "STAFF_NO_CONFLICT",
            "ASSIGNMENT_OVERLAP",
            "PRIMARY_ASSIGNMENT_CONFLICT",
            "POSITION_CAPACITY_EXCEEDED",
            "EFFECTIVE_DATE_INVALID",
            "RETROACTIVE_CHANGE_REQUIRES_APPROVAL",
            "CORRECTION_POLICY_DENIED",
            "MATERIAL_ACCESS_DENIED",
            "MATERIAL_VERSION_CONFLICT",
            "VERSION_CONFLICT",
            "LEGACY_AUTHORITY_MISMATCH",
            "AUTHORITY_UNAVAILABLE",
        }
        self.assertTrue(required.issubset(C.HR03_ERROR_CODES))

    def test_permissions_codes_present(self):
        for code in (
            "hr.staff.view",
            "hr.staff.reveal_high_sensitive",
            "hr.staff.material.download_sensitive",
            "hr.staff.correction.approve_high_risk",
            "hr.staff.audit.view",
        ):
            self.assertIn(code, C.HR_STAFF_PERMISSIONS)

    def test_assignment_types_match_book(self):
        self.assertEqual(
            set(C.AssignmentType.values),
            {"PRIMARY", "CONCURRENT", "TEMPORARY", "SECONDMENT"},
        )

    def test_sensitivity_levels(self):
        self.assertEqual(
            set(C.SensitivityLevel.values),
            {"PUBLIC_HR", "RESTRICTED_HR", "SENSITIVE", "HIGH_SENSITIVE"},
        )

    def test_staff_scope_types(self):
        self.assertEqual(
            set(C.StaffScopeType.values),
            {"SCHOOL", "COLLEGE", "DEPARTMENT", "ASSIGNMENT", "SELF", "EXPLICIT_STAFF_SET"},
        )

    def test_event_types(self):
        for event in ("StaffCreated", "PrimaryAssignmentChanged", "StaffAuthorityModeChanged"):
            self.assertIn(event, C.HR03_EVENT_TYPES)

    def test_correction_status_machine_has_apply_failed_tracking(self):
        self.assertIn(C.CorrectionStatus.FAILED, C.CorrectionStatus.values)

    def test_business_process_only_fields_are_locked_in_registry(self):
        from hr_staff.policies import FIELD_GOVERNANCE_REGISTRY

        for code, policy in FIELD_GOVERNANCE_REGISTRY.items():
            if code.startswith(("employment.", "assignment.", "staff.employment_status")):
                self.assertTrue(
                    policy.business_process_only,
                    f"{code} 应为 BUSINESS_PROCESS_ONLY",
                )
