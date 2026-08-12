import hashlib
from datetime import date

from django.test import TestCase, override_settings

from hr_qualification.constants import VerificationResult, VerificationType
from hr_qualification.crypto import decrypt_certificate_no, is_encrypted_certificate_no
from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential
from hr_qualification.selectors.credential_selector import CredentialSelector
from hr_qualification.services.credential_service import CredentialError, CredentialService
from hr_staff.models import HrPerson


@override_settings(SECRET_KEY="hr09-security-regression-secret")
class CertificateEncryptionRegressionTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=1, legal_name="安全测试人员")
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None,
            code="SECURITY-CERT",
            category="OTHER",
            name="Security Certificate",
        )

    def test_plain_certificate_bytes_are_encrypted_before_database_write(self):
        raw_no = "430102199001011234"
        item = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
            catalog_item_id=self.catalog,
            credential_name_snapshot=self.catalog.name,
            certificate_no_cipher=raw_no.encode("utf-8"),
            certificate_no_hash=hashlib.sha256(raw_no.encode()).hexdigest(),
            issuer_name="Issuer",
            valid_from=date(2026, 1, 1),
        )
        item.refresh_from_db()

        stored = bytes(item.certificate_no_cipher)
        self.assertNotEqual(stored, raw_no.encode("utf-8"))
        self.assertTrue(is_encrypted_certificate_no(stored))
        self.assertEqual(decrypt_certificate_no(1, stored), raw_no)

    def test_ciphertext_is_tenant_bound(self):
        raw_no = "CERT-998877"
        item = HrPersonCredential.objects.create(
            tenant_id=1,
            person_id=self.person,
            catalog_item_id=self.catalog,
            credential_name_snapshot=self.catalog.name,
            certificate_no_cipher=raw_no.encode(),
            certificate_no_hash=hashlib.sha256(raw_no.encode()).hexdigest(),
            issuer_name="Issuer",
        )
        item.refresh_from_db()
        with self.assertRaises(ValueError):
            decrypt_certificate_no(2, item.certificate_no_cipher)


class QualificationSecurityBoundaryRegressionTests(TestCase):
    def setUp(self):
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=None,
            code="BOUNDARY-CERT",
            category="OTHER",
            name="Boundary Certificate",
        )
        self.person1 = HrPerson.objects.create(tenant_id=1, legal_name="A 校人员")
        self.person2 = HrPerson.objects.create(tenant_id=2, legal_name="B 校人员")

    def _credential(self, tenant_id, person, number):
        return HrPersonCredential.objects.create(
            tenant_id=tenant_id,
            person_id=person,
            catalog_item_id=self.catalog,
            credential_name_snapshot=self.catalog.name,
            certificate_no_hash=hashlib.sha256(number.encode()).hexdigest(),
            issuer_name="Issuer",
            status="UNDER_VERIFICATION",
        )

    def test_exact_certificate_match_cannot_cross_tenant(self):
        number = "SAME-NO-ACROSS-SCHOOLS"
        a = self._credential(1, self.person1, number)
        b = self._credential(2, self.person2, number)

        self.assertEqual(CredentialSelector.exact_match_by_no(1, number).id, a.id)
        self.assertEqual(CredentialSelector.exact_match_by_no(2, number).id, b.id)

    def test_mock_provider_cannot_self_attest_verified_even_with_actor(self):
        credential = self._credential(1, self.person1, "MOCK-VERIFY")
        with self.assertRaises(CredentialError) as cm:
            CredentialService.verify(
                tenant_id=1,
                credential_id=credential.id,
                verification_type=VerificationType.MANUAL_ORIGINAL_REVIEW,
                result=VerificationResult.VERIFIED,
                verified_by=1001,
                provider="mock-national-registry",
            )
        self.assertEqual(cm.exception.code, "VERIFICATION_PROVIDER_NOT_TRUSTED")
        credential.refresh_from_db()
        self.assertEqual(credential.status, "UNDER_VERIFICATION")

    def test_public_non_manual_channel_cannot_create_verified_authority_fact(self):
        credential = self._credential(1, self.person1, "PUBLIC-VERIFY")
        with self.assertRaises(CredentialError) as cm:
            CredentialService.verify(
                tenant_id=1,
                credential_id=credential.id,
                verification_type="OFFICIAL_DATABASE",
                result=VerificationResult.VERIFIED,
                verified_by=1001,
                provider="official-looking-string",
            )
        self.assertEqual(cm.exception.code, "VERIFICATION_TRUSTED_PROVIDER_REQUIRED")
        credential.refresh_from_db()
        self.assertEqual(credential.status, "UNDER_VERIFICATION")

    def test_wrong_tenant_uuid_uses_generic_not_found_error(self):
        credential = self._credential(1, self.person1, "IDOR-TEST")
        with self.assertRaises(CredentialError) as cm:
            CredentialService._lock_credential(tenant_id=2, credential_id=credential.id)
        self.assertEqual(cm.exception.code, "CREDENTIAL_NOT_FOUND")
        self.assertNotIn("tenant 1", str(cm.exception).lower())
