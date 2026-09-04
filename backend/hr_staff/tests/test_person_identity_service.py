"""S2 · PersonIdentityService 测试：去重分层、加密/指纹/掩码。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import DuplicateMatchLevel
from hr_staff.models import HrPerson, HrPersonIdentityDocument
from hr_staff.services.crypto import (
    decrypt_document_number,
    document_fingerprint,
    encrypt_document_number,
    mask_document_number,
    normalize_document_number,
)
from hr_staff.services.person_identity_service import (
    PersonDuplicateHardMatch,
    PersonDuplicateReviewRequired,
    PersonIdentityService,
)

ID_NO = "110101199001011234"


class CryptoHelperTests(TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_document_number("110101 19900101 1234"), "110101199001011234")

    def test_roundtrip_encrypt_decrypt(self):
        cipher = encrypt_document_number(1, ID_NO)
        self.assertNotIn(ID_NO, cipher)
        self.assertEqual(decrypt_document_number(cipher), ID_NO)

    def test_mask(self):
        self.assertEqual(mask_document_number("110101199001011234"), "110101****1234")
        self.assertEqual(mask_document_number("123"), "***")


class PersonIdentityServiceTests(TestCase):
    def setUp(self):
        self.service = PersonIdentityService()

    def test_create_person_with_identity_masked(self):
        person = self.service.create_person_with_identity(
            tenant_id=1,
            legal_name="张三",
            document_number=ID_NO,
        )
        doc = person.identity_documents.get()
        self.assertEqual(doc.masked_display, "110101****1234")
        self.assertEqual(doc.document_number_fingerprint, document_fingerprint_of(1))
        self.assertEqual(decrypt_document_number(doc.document_number_ciphertext), ID_NO)

    def test_hard_match_same_name_returns_existing_person(self):
        """HARD 命中且姓名一致 → 幂等返回已有 Person。"""
        first = self.service.create_person_with_identity(tenant_id=1, legal_name="张三", document_number=ID_NO)
        second = self.service.create_person_with_identity(tenant_id=1, legal_name="张三", document_number=ID_NO)
        self.assertEqual(first.id, second.id)
        self.assertEqual(HrPerson.objects.filter(tenant_id=1).count(), 1)

    def test_hard_match_different_name_raises(self):
        """P2-15：HARD 命中但姓名不同 → 不得静默复用他人 Person。"""
        self.service.create_person_with_identity(tenant_id=1, legal_name="张三", document_number=ID_NO)
        with self.assertRaises(PersonDuplicateHardMatch):
            self.service.create_person_with_identity(tenant_id=1, legal_name="张三三", document_number=ID_NO)

    def test_same_number_different_tenant_allowed(self):
        a = self.service.create_person_with_identity(tenant_id=1, legal_name="张三", document_number=ID_NO)
        b = self.service.create_person_with_identity(tenant_id=2, legal_name="张三", document_number=ID_NO)
        self.assertNotEqual(a.id, b.id)

    def test_likely_match_requires_review(self):
        self.service.create_person_with_identity(
            tenant_id=1, legal_name="王五", birth_date=date(1990, 1, 1)
        )
        # LIKELY 命中 → 必须人工去重，绝不自动合并、绝不静默新建
        with self.assertRaises(PersonDuplicateReviewRequired):
            self.service.create_person_with_identity(
                tenant_id=1,
                legal_name="王五",
                birth_date=date(1990, 1, 1),
            )

    def test_no_match_creates(self):
        dedup = self.service.find_duplicate(1, document_number=ID_NO)
        self.assertEqual(dedup.level, DuplicateMatchLevel.NO_MATCH)

    def test_upsert_identity_cross_person_raises_hard_match(self):
        person = self.service.create_person_with_identity(tenant_id=1, legal_name="张三", document_number=ID_NO)
        other = HrPerson.objects.create(tenant_id=1, legal_name="赵六")
        with self.assertRaises(PersonDuplicateHardMatch):
            self.service._upsert_identity_document(
                tenant_id=1,
                person=other,
                document_type="NATIONAL_ID",
                document_number=ID_NO,
                valid_from=None,
                valid_to=None,
            )
        self.assertEqual(person.identity_documents.count(), 1)


def document_fingerprint_of(tenant_id):
    return document_fingerprint(tenant_id, normalize_document_number(ID_NO))
