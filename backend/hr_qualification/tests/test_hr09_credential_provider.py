"""HR09 local credential provider contracts."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_qualification.constants import (
    CredentialCategory,
    CredentialStatus,
    ProviderStatus,
    VerificationResult,
)
from hr_qualification.models import (
    HrCredentialCatalogItem,
    HrCredentialDocument,
    HrPersonCredential,
)
from hr_qualification.providers.hr09 import Hr09CredentialProvider
from hr_staff.models import HrPerson, HrStaffMaster


class Hr09CredentialProviderTests(TestCase):
    def setUp(self):
        self.tenant_id = 84123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Credential provider",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no=f"CRED-{uuid.uuid4().hex}",
        )
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=self.tenant_id,
            code=f"VQ-{uuid.uuid4().hex[:8]}",
            category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            name="职业资格",
            level_schema={
                "levels": [
                    {"code": "LEVEL_3", "name": "高级工", "rank": 3},
                    {"code": "LEVEL_2", "name": "技师", "rank": 4},
                ]
            },
            requires_document=True,
        )

    def _credential(self, *, status=CredentialStatus.ACTIVE, level_code="LEVEL_2"):
        today = timezone.localdate()
        return HrPersonCredential.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_master_id=self.staff,
            catalog_item_id=self.catalog,
            credential_name_snapshot=self.catalog.name,
            level_code=level_code,
            issuer_name="Authority",
            valid_from=today - timedelta(days=100),
            valid_to=(today - timedelta(days=1)) if status == CredentialStatus.EXPIRED else None,
            status=status,
            current_verification_status=VerificationResult.VERIFIED,
            last_verified_at=timezone.now(),
        )

    def test_active_credential_exposes_catalog_rank_and_verified_document(self):
        credential = self._credential()
        document = HrCredentialDocument.objects.create(
            credential_id=credential,
            file_id=f"file-{uuid.uuid4().hex}",
            verified=True,
            checksum="a" * 64,
        )

        result = Hr09CredentialProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=timezone.localdate(),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.source_domain, "HR09_CREDENTIAL")
        self.assertEqual(item.quantitative_value, 4.0)
        self.assertEqual(item.verification_status, VerificationResult.VERIFIED)
        self.assertEqual(item.document_refs, [document.file_id])
        self.assertEqual(item.snapshot_json["level_rank"], 4)
        self.assertTrue(item.snapshot_json["requires_document"])

    def test_active_credential_without_verification_never_defaults_to_verified(self):
        today = timezone.localdate()
        HrPersonCredential.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_master_id=self.staff,
            catalog_item_id=self.catalog,
            credential_name_snapshot=self.catalog.name,
            level_code="LEVEL_2",
            issuer_name="Authority",
            valid_from=today - timedelta(days=30),
            status=CredentialStatus.ACTIVE,
            current_verification_status="",
            last_verified_at=None,
        )

        result = Hr09CredentialProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=today,
        )

        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertEqual(
            result.items[0].verification_status,
            VerificationResult.NEEDS_MANUAL_REVIEW,
        )
        self.assertTrue(
            any(error.code == "CREDENTIAL_VERIFICATION_UNPROVEN" for error in result.errors)
        )

    def test_expired_credential_never_surfaces_as_verified_active_evidence(self):
        self._credential(status=CredentialStatus.EXPIRED)

        result = Hr09CredentialProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=timezone.localdate(),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.items[0].verification_status, CredentialStatus.EXPIRED)

    def test_wrong_person_staff_mapping_is_unavailable(self):
        other = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="other",
        )
        result = Hr09CredentialProvider().provide(
            person_id=other.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=timezone.localdate(),
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")
