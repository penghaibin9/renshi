"""Database regressions for formal staff roster readback after school import.

Fixtures populate real service-created staff outside the query-measurement
window. They are selector tests, not a substitute for browser import proof.
"""

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from hr_staff.constants import AssignmentType
from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.selectors.staff_list import STAFF_LIST_FIELDS, StaffListSelector
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff
from hr_structure.models import HrOrganizationVersion
from hr_structure.selectors.effective import org_version_as_of

TENANT = 730310
OTHER_TENANT = 730311
AS_OF = date(2024, 9, 1)


class StaffListFormalReadbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = make_org(TENANT, "READBACK-OFFICE", "已生效教务处", AS_OF)
        cls.foreign_org = make_org(OTHER_TENANT, "READBACK-OFFICE", "另一学校教务处", AS_OF)
        for number in range(50):
            cls._create_staff(TENANT, cls.organization, f"READBACK-{number:03d}")
        cls._create_staff(OTHER_TENANT, cls.foreign_org, "READBACK-000")

    @staticmethod
    def _create_staff(tenant_id, organization, staff_no):
        person = make_person(tenant_id, "测试教职工 " + staff_no)
        staff = make_staff(tenant_id, person, staff_no)
        relation = EmploymentService(tenant_id).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=AS_OF,
            source_business_type="MIGRATION_VERIFIED",
        )
        AssignmentService(tenant_id).create_assignment(
            employment_relationship_id=relation,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=AS_OF,
            organization_id=organization,
            source_business_type="MIGRATION_VERIFIED",
        )

    def selector(self, *, as_of=AS_OF, tenant_id=TENANT):
        return StaffListSelector(HrStaffRequestContext(
            tenant_id=tenant_id, as_of=as_of, scope=HrStaffScope("SCHOOL")
        ))

    def add_version(self, *, status, version_no=2, name="未生效改名", start=AS_OF, end=None):
        return HrOrganizationVersion.objects.create(
            tenant_id=TENANT, organization_id=self.organization,
            name=name, org_type="COLLEGE", status=status,
            version_no=version_no, validity_from=start, validity_to=end,
        )

    def test_draft_rejected_and_cancelled_names_never_replace_formal_name(self):
        for index, status in enumerate(("DRAFT", "REJECTED", "CANCELLED"), 2):
            self.add_version(status=status, version_no=index, name=f"不应展示-{status}")
        rows = self.selector().rows({}, page_size=50)
        canonical = org_version_as_of(TENANT, self.organization.pk, AS_OF)
        self.assertEqual(rows["total"], 50)
        self.assertEqual({row["org_name"] for row in rows["items"]}, {canonical.name})
        self.assertEqual(canonical.name, "已生效教务处")

    def test_formal_name_changes_only_at_half_open_effective_boundary(self):
        boundary = AS_OF + timedelta(days=1)
        HrOrganizationVersion.objects.filter(
            tenant_id=TENANT, organization_id=self.organization, version_no=1
        ).update(validity_to=boundary, status="SUPERSEDED")
        self.add_version(status="APPROVED", name="新名称教务处", start=boundary)
        self.add_version(status="DRAFT", version_no=3, name="更高版本草稿")
        for day, expected in ((AS_OF, "已生效教务处"), (boundary, "新名称教务处")):
            with self.subTest(as_of=day):
                rows = self.selector(as_of=day).rows({}, page_size=50)
                self.assertEqual({row["org_name"] for row in rows["items"]}, {expected})
                self.assertEqual(org_version_as_of(TENANT, self.organization.pk, day).name, expected)

    def test_name_lookup_remains_scoped_even_for_a_foreign_reference(self):
        from types import SimpleNamespace

        primaries = [SimpleNamespace(organization_id_id=self.foreign_org.pk)]
        self.assertEqual(self.selector()._batch_org_names(primaries), {})
        own = self.selector().rows({}, page_size=50)
        foreign = self.selector(tenant_id=OTHER_TENANT).rows({}, page_size=50)
        self.assertEqual(own["total"], 50)
        self.assertEqual(foreign["total"], 1)
        self.assertEqual({row["org_name"] for row in foreign["items"]}, {"另一学校教务处"})
        self.assertTrue(all(set(row) == STAFF_LIST_FIELDS for row in own["items"]))

    def test_no_formal_name_falls_back_to_code_never_to_draft(self):
        HrOrganizationVersion.objects.filter(
            tenant_id=TENANT, organization_id=self.organization
        ).update(status="CANCELLED")
        self.add_version(status="DRAFT", name="不能伪装已生效")
        rows = self.selector().rows({}, page_size=50)
        self.assertEqual({row["org_name"] for row in rows["items"]}, {"READBACK-OFFICE"})

    def test_one_and_fifty_rows_have_the_same_bounded_sql_count(self):
        with CaptureQueriesContext(connection) as one:
            single = self.selector().rows({}, page_size=1)
        with CaptureQueriesContext(connection) as fifty:
            full = self.selector().rows({}, page_size=50)
        self.assertEqual(len(single["items"]), 1)
        self.assertEqual(len(full["items"]), 50)
        self.assertEqual(full["total"], 50)
        self.assertEqual(len(one), len(fifty), "SQL count must not grow once per staff row")
        self.assertLessEqual(len(fifty), 12, "A 50-row roster must remain within its query budget")
        self.assertEqual({row["org_name"] for row in full["items"]}, {"已生效教务处"})
