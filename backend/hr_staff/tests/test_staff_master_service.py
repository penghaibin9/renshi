"""S2 · StaffMasterService 测试：工号生成、冲突、canonical 防重。"""

from django.test import TestCase

from hr_staff.models import HrPerson
from hr_staff.services.staff_master_service import (
    DuplicateStaffMaster,
    StaffMasterService,
    StaffNoConflict,
    StaffNumberService,
)


class StaffNumberServiceTests(TestCase):
    def test_generates_incrementing_numbers(self):
        svc = StaffNumberService(prefix="T", width=6)
        tenant = 1
        self.assertEqual(svc.next_staff_no(tenant), "T000001")
        from hr_staff.models import HrStaffMaster

        person = HrPerson.objects.create(tenant_id=tenant, legal_name="A")
        HrStaffMaster.objects.create(tenant_id=tenant, person_id=person, staff_no="T000001")
        self.assertEqual(svc.next_staff_no(tenant), "T000002")


class StaffMasterServiceTests(TestCase):
    def setUp(self):
        self.service = StaffMasterService(StaffNumberService(prefix="T", width=6))
        self.tenant = 1

    def test_create_staff(self):
        person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="张三")
        staff = self.service.create_staff(tenant_id=self.tenant, person_id=person)
        self.assertTrue(staff.staff_no.startswith("T"))
        self.assertEqual(staff.tenant_id, self.tenant)

    def test_staff_no_conflict(self):
        person_a = HrPerson.objects.create(tenant_id=self.tenant, legal_name="A1")
        self.service.create_staff(tenant_id=self.tenant, person_id=person_a, staff_no="T000001")
        person_b = HrPerson.objects.create(tenant_id=self.tenant, legal_name="A2")
        with self.assertRaises(StaffNoConflict):
            self.service.create_staff(
                tenant_id=self.tenant, person_id=person_b, staff_no="T000001"
            )

    def test_duplicate_staff_for_person_rejected(self):
        person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="B")
        self.service.create_staff(tenant_id=self.tenant, person_id=person)
        with self.assertRaises(DuplicateStaffMaster):
            self.service.create_staff(tenant_id=self.tenant, person_id=person)

    def test_legacy_mapping_lookup(self):
        person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="C")
        staff = self.service.create_staff(
            tenant_id=self.tenant, person_id=person, legacy_employee_id=42
        )
        self.assertEqual(
            self.service.get_by_legacy_employee(self.tenant, 42).id, staff.id
        )
