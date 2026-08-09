"""S7 · BackgroundService/BackgroundSelector 测试：多条结构化、最高学历唯一、证号掩码。"""

from datetime import date

from django.test import TestCase

from hr_staff.context import HrStaffRequestContext, HrStaffScope
from hr_staff.models import HrCredential, HrEducationExperience
from hr_staff.selectors.backgrounds import BackgroundSelector, StaffNotFound
from hr_staff.services.background_service import BackgroundService
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1


def ctx():
    return HrStaffRequestContext(tenant_id=TENANT, scope=HrStaffScope(scope_type="SCHOOL"))


class BackgroundServiceTests(TestCase):
    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T001238")
        self.svc = BackgroundService(TENANT, has_manage_perm=True)

    def test_add_multiple_education_records(self):
        self.svc.add_education(
            staff_id=self.staff,
            school_name="湖南大学",
            education_level="博士研究生",
            major_name="计算机科学与技术",
            start_date=date(2016, 9, 1),
            end_date=date(2020, 6, 30),
            is_highest_education=True,
        )
        self.svc.add_education(
            staff_id=self.staff,
            school_name="武汉大学",
            education_level="本科",
            major_name="软件工程",
            start_date=date(2012, 9, 1),
            end_date=date(2016, 6, 30),
        )
        self.assertEqual(
            HrEducationExperience.objects.filter(tenant_id=TENANT, staff_id=self.staff).count(), 2
        )
        # 最高学历唯一
        highest = HrEducationExperience.objects.filter(
            tenant_id=TENANT, staff_id=self.staff, is_highest_education=True
        ).count()
        self.assertEqual(highest, 1)

    def test_highest_education_moves_when_new_higher_added(self):
        first = self.svc.add_education(
            staff_id=self.staff, school_name="A", education_level="硕士", is_highest_education=True
        )
        second = self.svc.add_education(
            staff_id=self.staff, school_name="B", education_level="博士", is_highest_education=True
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_highest_education)
        self.assertTrue(second.is_highest_education)

    def test_credential_number_masked(self):
        cred = self.svc.add_credential(
            staff_id=self.staff,
            credential_type="TEACHER_QUALIFICATION",
            credential_name="高校教师资格证",
            credential_no="1101011988",
        )
        self.assertEqual(cred.credential_no_masked, "11****88")

    def test_bundle_contains_all_sections(self):
        self.svc.add_education(staff_id=self.staff, school_name="A", education_level="本科")
        self.svc.add_degree(staff_id=self.staff, degree_level="学士", degree_name="工学学士")
        self.svc.add_work_experience(staff_id=self.staff, organization_name="某高校")
        self.svc.add_credential(staff_id=self.staff, credential_type="OTHER", credential_name="普通话")
        self.svc.add_talent_honor(staff_id=self.staff, honor_name="省级人才")
        data = BackgroundSelector(ctx()).bundle(self.staff.id)
        self.assertEqual(len(data["education"]), 1)
        self.assertEqual(len(data["degrees"]), 1)
        self.assertEqual(len(data["workExperience"]), 1)
        self.assertEqual(len(data["credentials"]), 1)
        self.assertEqual(len(data["talentHonors"]), 1)

    def test_credential_no_plaintext_never_serialized(self):
        self.svc.add_credential(
            staff_id=self.staff,
            credential_type="OTHER",
            credential_name="证书",
            credential_no="SECRET123456",
        )
        data = BackgroundSelector(ctx()).bundle(self.staff.id)
        self.assertNotIn("SECRET123456", str(data))

    def test_staff_not_found(self):
        import uuid

        with self.assertRaises(StaffNotFound):
            BackgroundSelector(ctx()).bundle(uuid.uuid4())
