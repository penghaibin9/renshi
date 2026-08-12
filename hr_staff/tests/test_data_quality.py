"""S12b · DataQualityService 测试：异常类型扫描。"""

from datetime import date

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
