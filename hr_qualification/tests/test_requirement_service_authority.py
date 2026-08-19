"""Requirement helper authority and overlap contracts."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_qualification.constants import (
    CredentialCategory,
    CredentialStatus,
    RequirementMatchResult,
    VerificationResult,
)
from hr_qualification.models import (
    HrCredentialCatalogItem,
    HrCredentialRequirement,
    HrPersonCredential,
)
from hr_qualification.services.requirement_service import RequirementService
from hr_staff.constants import VerificationStatus
from hr_staff.models import HrPerson, HrStaffMaster, HrWorkExperience


class RequirementServiceAuthorityTests(TestCase):
    def setUp(self):
        self.tenant_id = 88123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="Requirement authority",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no=f"REQ-{uuid.uuid4().hex}",
        )
        self.catalog = HrCredentialCatalogItem.objects.create(
            tenant_id=self.tenant_id,
            code=f"REQ-CAT-{uuid.uuid4().hex[:8]}",
            category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            name="职业资格",
            level_schema={
                "levels": [
                    {"code": "LEVEL_3", "rank": 3},
                    {"code": "LEVEL_2", "rank": 4},
                ]
            },
        )

    def _active_credential(self, **overrides):
        today = timezone.localdate()
        data = {
            "tenant_id": self.tenant_id,
            "person_id": self.person,
            "staff_master_id": self.staff,
            "catalog_item_id": self.catalog,
            "credential_name_snapshot": self.catalog.name,
            "level_code": "LEVEL_2",
            "issuer_name": "Authority",
            "valid_from": today - timedelta(days=30),
            "status": CredentialStatus.ACTIVE,
            "current_verification_status": VerificationResult.VERIFIED,
            "last_verified_at": timezone.now(),
        }
        data.update(overrides)
        return HrPersonCredential.objects.create(**data)

    def test_level_parameter_is_exact_not_ignored(self):
        today = timezone.localdate()
        self._active_credential()
        service = RequirementService()
        self.assertTrue(
            service.has_qualification(
                self.tenant_id,
                self.staff.id,
                CredentialCategory.VOCATIONAL_QUALIFICATION,
                level="LEVEL_2",
                as_of=today,
            )
        )
        self.assertFalse(
            service.has_qualification(
                self.tenant_id,
                self.staff.id,
                CredentialCategory.VOCATIONAL_QUALIFICATION,
                level="LEVEL_1",
                as_of=today,
            )
        )

    def test_active_but_unverified_credential_is_not_a_satisfied_qualification(self):
        today = timezone.localdate()
        self._active_credential(
            current_verification_status=VerificationResult.NEEDS_MANUAL_REVIEW
        )

        self.assertFalse(
            RequirementService().has_qualification(
                self.tenant_id,
                self.staff.id,
                CredentialCategory.VOCATIONAL_QUALIFICATION,
                level="LEVEL_2",
                as_of=today,
            )
        )

    def test_compare_person_to_requirement_restores_api_authority_contract(self):
        credential = self._active_credential(level_code="LEVEL_2")
        requirement = HrCredentialRequirement.objects.create(
            tenant_id=self.tenant_id,
            credential_category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            catalog_item_id=self.catalog,
            minimum_level="LEVEL_3",
            verification_required=True,
            valid_on_date_required=True,
        )

        match = RequirementService.compare_person_to_requirement(
            credential,
            requirement,
            as_of=timezone.localdate(),
        )

        self.assertEqual(match.result, RequirementMatchResult.MET)
        self.assertEqual(match.matched_credential_id, str(credential.id))

    def test_compare_person_to_requirement_fails_closed_when_rank_is_unprovable(self):
        credential = self._active_credential(level_code="UNKNOWN_LEVEL")
        requirement = HrCredentialRequirement.objects.create(
            tenant_id=self.tenant_id,
            credential_category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            minimum_level="LEVEL_3",
            verification_required=True,
        )

        match = RequirementService.compare_person_to_requirement(
            credential,
            requirement,
            as_of=timezone.localdate(),
        )

        self.assertEqual(match.result, RequirementMatchResult.LOWER_LEVEL)
        self.assertIn("does not prove", match.detail)

    def test_valid_to_uses_half_open_boundary(self):
        today = timezone.localdate()
        credential = self._active_credential(valid_to=today)
        requirement = HrCredentialRequirement.objects.create(
            tenant_id=self.tenant_id,
            credential_category=CredentialCategory.VOCATIONAL_QUALIFICATION,
            valid_on_date_required=True,
        )

        match = RequirementService.compare_person_to_requirement(
            credential,
            requirement,
            as_of=today,
        )

        self.assertEqual(match.result, RequirementMatchResult.EXPIRED)

    def test_unverified_work_is_not_counted(self):
        today = timezone.localdate()
        HrWorkExperience.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff,
            organization_name="Unverified Co",
            position_title="Engineer",
            experience_type=HrWorkExperience.ExperienceType.ENTERPRISE,
            start_date=today - timedelta(days=500),
            verification_status=VerificationStatus.PENDING,
        )
        self.assertFalse(
            RequirementService().has_min_experience_days(
                self.tenant_id,
                self.staff.id,
                HrWorkExperience.ExperienceType.ENTERPRISE,
                365,
                as_of=today,
            )
        )

    def test_overlapping_verified_work_is_not_double_counted(self):
        today = timezone.localdate()
        for start_days, end_days in ((300, 100), (250, 50)):
            HrWorkExperience.objects.create(
                tenant_id=self.tenant_id,
                staff_id=self.staff,
                organization_name=f"Verified Co {start_days}",
                position_title="Engineer",
                experience_type=HrWorkExperience.ExperienceType.ENTERPRISE,
                start_date=today - timedelta(days=start_days),
                end_date=today - timedelta(days=end_days),
                verification_status=VerificationStatus.VERIFIED,
            )
        service = RequirementService()
        self.assertFalse(
            service.has_min_experience_days(
                self.tenant_id,
                self.staff.id,
                HrWorkExperience.ExperienceType.ENTERPRISE,
                300,
                as_of=today,
            )
        )
        self.assertTrue(
            service.has_min_experience_days(
                self.tenant_id,
                self.staff.id,
                HrWorkExperience.ExperienceType.ENTERPRISE,
                250,
                as_of=today,
            )
        )
