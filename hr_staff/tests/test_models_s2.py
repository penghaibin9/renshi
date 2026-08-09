"""S2 · 权威模型约束测试：tenant 隔离、staff_no 唯一、canonical StaffMaster、fingerprint 去重。

注意：SQLite 下约束冲突会破坏外层 TestCase 事务，违反场景必须用
`assertRaises + 嵌套 transaction.atomic()` 让冲突回滚到 savepoint。
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_staff.models import (
    HrPerson,
    HrPersonIdentityDocument,
    HrStaffMaster,
)
from hr_staff.services.crypto import document_fingerprint, normalize_document_number


class TenantIsolationTests(TestCase):
    def test_person_tenant_private(self):
        p_a = HrPerson.objects.create(tenant_id=1, legal_name="张三")
        HrPerson.objects.create(tenant_id=2, legal_name="李四")
        self.assertEqual(
            set(HrPerson.objects.filter(tenant_id=1).values_list("id", flat=True)),
            {p_a.id},
        )

    def test_staff_no_unique_per_tenant(self):
        HrStaffMaster.objects.create(
            tenant_id=1, person_id=HrPerson.objects.create(tenant_id=1, legal_name="A"), staff_no="T000001"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrStaffMaster.objects.create(
                    tenant_id=1,
                    person_id=HrPerson.objects.create(tenant_id=1, legal_name="B"),
                    staff_no="T000001",
                )
        # 另一 tenant 可用相同 staff_no
        HrStaffMaster.objects.create(
            tenant_id=2, person_id=HrPerson.objects.create(tenant_id=2, legal_name="C"), staff_no="T000001"
        )

    def test_canonical_single_staff_per_person(self):
        person = HrPerson.objects.create(tenant_id=1, legal_name="D")
        HrStaffMaster.objects.create(tenant_id=1, person_id=person, staff_no="T1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrStaffMaster.objects.create(tenant_id=1, person_id=person, staff_no="T2")


class IdentityFingerprintTests(TestCase):
    def test_fingerprint_is_tenant_aware(self):
        fp_a = document_fingerprint(1, normalize_document_number("110101199001011234"))
        fp_b = document_fingerprint(2, normalize_document_number("110101199001011234"))
        self.assertNotEqual(fp_a, fp_b)
        self.assertEqual(len(fp_a), 64)

    def test_duplicate_fingerprint_same_tenant_rejected(self):
        person = HrPerson.objects.create(tenant_id=1, legal_name="E")
        HrPersonIdentityDocument.objects.create(
            tenant_id=1,
            person_id=person,
            document_type="NATIONAL_ID",
            document_number_fingerprint=document_fingerprint(
                1, normalize_document_number("110101199001011234")
            ),
            masked_display="110101****1234",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrPersonIdentityDocument.objects.create(
                    tenant_id=1,
                    person_id=person,
                    document_type="PASSPORT",
                    document_number_fingerprint=document_fingerprint(
                        1, normalize_document_number("110101199001011234")
                    ),
                )
