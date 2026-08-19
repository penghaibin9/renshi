"""Requirement helper authority and overlap contracts."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from hr_qualification.constants import (
    CredentialCategory,
    CredentialStatus,
    VerificationResult,
)
from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential
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
            level_schema={"levels": [{"code": "LEVEL_2", "rank": 4}]},
        )

    def test_level_parameter_is_exact_not_ignored(self):
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
            current_verification_status=VerificationResult.VERIFIED,
            last_verified_at=timezone.now(),
        )
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
