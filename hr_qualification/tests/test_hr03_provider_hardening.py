"""HR03 background provider production contracts."""

import uuid
from datetime import date

from django.test import TestCase

from hr_qualification.constants import ProviderStatus
from hr_qualification.providers.hr03 import (
    Hr03EducationProvider,
    Hr03WorkHistoryProvider,
)
from hr_staff.constants import VerificationStatus
from hr_staff.models import (
    HrDegreeRecord,
    HrEducationExperience,
    HrPerson,
    HrStaffMaster,
    HrWorkExperience,
)


class Hr03BackgroundProviderHardeningTests(TestCase):
    def setUp(self):
        self.tenant_id = 83123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="HR03 background",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no=f"BG-{uuid.uuid4().hex}",
        )

    def _education(self, *, status=VerificationStatus.VERIFIED, end_date=date(2026, 6, 30)):
        return HrEducationExperience.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff,
            school_name="Verified University",
            education_level="MASTER",
            major_name="Education",
            start_date=date(2024, 9, 1),
            end_date=end_date,
            verification_status=status,
        )

    def _degree(self, *, status=VerificationStatus.VERIFIED, awarded=date(2026, 6, 30)):
        return HrDegreeRecord.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff,
            degree_level="MASTER",
            degree_name="Master of Education",
            granting_institution="Verified University",
            awarded_date=awarded,
            verification_status=status,
        )

    def _work(
        self,
        *,
        status=VerificationStatus.VERIFIED,
        start=date(2026, 1, 1),
        end=None,
    ):
        return HrWorkExperience.objects.create(
            tenant_id=self.tenant_id,
            staff_id=self.staff,
            organization_name="Industry Co",
            position_title="Engineer",
            experience_type=HrWorkExperience.ExperienceType.ENTERPRISE,
            start_date=start,
            end_date=end,
            verification_status=status,
        )

    def test_education_provider_excludes_unverified_and_future_completion(self):
        expected = self._education()
        expected_degree = self._degree()
        self._education(status=VerificationStatus.PENDING)
        self._degree(status=VerificationStatus.REJECTED)
        self._education(end_date=date(2027, 6, 30))
        self._degree(awarded=date(2027, 6, 30))

        result = Hr03EducationProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        # This contract is about eligibility/exclusion, not presentation order;
        # the source-owned HR03 contract may deterministically order equal-date
        # education and degree facts without changing the evidence set.
        self.assertCountEqual(
            [item.source_object_id for item in result.items],
            [str(expected.id), str(expected_degree.id)],
        )
        self.assertTrue(all(item.verification_status == VerificationStatus.VERIFIED for item in result.items))
        self.assertEqual(
            result.source_updated_at,
            max(expected.updated_at, expected_degree.updated_at),
        )

    def test_work_duration_is_capped_at_as_of_not_today(self):
        work = self._work(start=date(2026, 1, 1), end=None)

        result = Hr03WorkHistoryProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=date(2026, 2, 1),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual([item.source_object_id for item in result.items], [str(work.id)])
        self.assertEqual(result.items[0].quantitative_value, 31.0)
        self.assertEqual(result.items[0].snapshot_json["durationDaysAsOf"], 31)

    def test_future_and_unverified_work_are_not_evidence(self):
        self._work(start=date(2026, 9, 1))
        self._work(status=VerificationStatus.UNVERIFIED)

        result = Hr03WorkHistoryProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.items, [])
        self.assertIsNone(result.source_updated_at)

    def test_wrong_person_staff_pair_is_unavailable_not_not_applicable(self):
        other = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="other",
        )

        result = Hr03EducationProvider().provide(
            person_id=other.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")

    def test_unknown_source_version_fails_closed(self):
        result = Hr03WorkHistoryProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=self.tenant_id,
            as_of=date(2026, 8, 1),
            source_version="legacy-background-v0",
        )

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_VERSION_UNSUPPORTED")
