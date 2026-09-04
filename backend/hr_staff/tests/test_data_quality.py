"""S12b · DataQualityService 测试：异常类型扫描。"""

from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.data_quality_service import DataQualityService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


class DataQualityServiceTests(TestCase):
    def test_active_without_primary_detected(self):
        """ACTIVE 但无主岗 → PRIMARY_ASSIGNMENT_MISSING（HIGH）。"""
        staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T100001")
        EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        result = DataQualityService(TENANT).scan()
        rules = {i["rule"] for i in result["issues"]}
        self.assertIn("PRIMARY_ASSIGNMENT_MISSING", rules)

    def test_org_mapping_missing_detected(self):
        """任职仅 legacy 映射 → ORG_MAPPING_MISSING（LOW）。"""
        staff = make_staff(TENANT, make_person(TENANT, "李四"), "T100002")
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=None,
            legacy_department_id=7,
            source_business_type=FIXTURE_SOURCE,
        )
        result = DataQualityService(TENANT).scan()
        rules = {i["rule"] for i in result["issues"]}
        self.assertIn("ORG_MAPPING_MISSING", rules)

    def test_clean_staff_no_high_issues(self):
        org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        staff = make_staff(TENANT, make_person(TENANT, "王五"), "T100003")
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=org,
            source_business_type=FIXTURE_SOURCE,
        )
        result = DataQualityService(TENANT).scan()
        staff_rules = [i for i in result["issues"] if i["staffNo"] == "T100003"]
        self.assertFalse(
            any(r["severity"] == "HIGH" for r in staff_rules),
            f"clean staff should not have HIGH issues: {staff_rules}",
        )

    def test_legacy_mapping_does_not_create_placeholder_mismatch(self):
        staff = make_staff(TENANT, make_person(TENANT, "赵六"), "T100004")
        staff.legacy_employee_id = 41
        staff.save(update_fields=["legacy_employee_id"])
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=make_org(TENANT, "WGY", "外国语学院", date(2020, 1, 1)),
            source_business_type=FIXTURE_SOURCE,
        )
        legacy = SimpleNamespace(
            badge_id="T100004",
            is_active=True,
            employee_work_info=SimpleNamespace(
                date_joining=date(2024, 9, 1),
                department_id_id=None,
                job_position_id_id=None,
            ),
        )
        with mock.patch(
            "hr_staff.legacy.reconciliation.ReconciliationService._legacy_employee",
            return_value=legacy,
        ):
            result = DataQualityService(TENANT, as_of=date(2025, 1, 1)).scan()
        rules = {i["rule"] for i in result["issues"] if i["staffNo"] == "T100004"}
        self.assertNotIn("LEGACY_AUTHORITY_MISMATCH", rules)

    def test_actual_legacy_difference_lists_only_mismatched_dimensions(self):
        staff = make_staff(TENANT, make_person(TENANT, "钱七"), "T100005")
        staff.legacy_employee_id = 42
        staff.save(update_fields=["legacy_employee_id"])
        EmploymentService(TENANT).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        legacy = SimpleNamespace(
            badge_id="OTHER-NO",
            is_active=True,
            employee_work_info=SimpleNamespace(
                date_joining=date(2024, 9, 1),
                department_id_id=None,
                job_position_id_id=None,
            ),
        )
        with mock.patch(
            "hr_staff.legacy.reconciliation.ReconciliationService._legacy_employee",
            return_value=legacy,
        ):
            result = DataQualityService(TENANT, as_of=date(2025, 1, 1)).scan()
        mismatch = next(
            i for i in result["issues"]
            if i["staffNo"] == "T100005" and i["rule"] == "LEGACY_AUTHORITY_MISMATCH"
        )
        self.assertEqual(mismatch["message"], "新旧数据不一致：工号")
        self.assertNotIn("OTHER-NO", mismatch["message"])
