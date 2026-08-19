"""HR08 qualification provider production contracts."""

import uuid
from datetime import date

from django.test import TestCase

from hr_external.constants import ExternalEngagementStatus
from hr_external.models import (
    HrExternalCategory,
    HrExternalEngagement,
    HrExternalTeacherProfile,
)
from hr_qualification.constants import ProviderStatus
from hr_qualification.providers.hr08 import Hr08EngagementProvider
from hr_staff.models import HrPerson


class Hr08EngagementProviderHardeningTests(TestCase):
    def setUp(self):
        self.tenant_id = 82123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="HR08 evidence",
        )
        self.category = HrExternalCategory.objects.create(
            tenant_id=self.tenant_id,
            code=f"INDUSTRY-{uuid.uuid4().hex[:8]}",
            name="Industry Mentor",
        )
        self.profile = HrExternalTeacherProfile.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            external_teacher_no=f"EXT-{uuid.uuid4().hex[:10]}",
            primary_category=self.category,
        )

    def _engagement(self, *, status, start_at=date(2026, 7, 1), end_at=None, category=None):
        return HrExternalEngagement.objects.create(
            tenant_id=self.tenant_id,
            engagement_no=f"ENG-{uuid.uuid4().hex[:10]}",
            person_id=self.person,
            external_profile_id=self.profile,
            category_id=category or self.category,
            host_organization_id=9001,
            start_at=start_at,
            end_at=end_at,
            status=status,
        )

    def _provide(self, as_of=date(2026, 8, 1)):
        return Hr08EngagementProvider().provide(
            person_id=self.person.id,
            staff_master_id=None,
            tenant_id=self.tenant_id,
            as_of=as_of,
        )

    def test_draft_and_future_engagements_are_not_eligibility_evidence(self):
        self._engagement(status=ExternalEngagementStatus.DRAFT)
        self._engagement(
            status=ExternalEngagementStatus.ACTIVE,
            start_at=date(2026, 9, 1),
        )

        result = self._provide()

        self.assertEqual(result.status, ProviderStatus.NOT_APPLICABLE)
        self.assertEqual(result.items, [])

    def test_ended_current_row_still_proves_earlier_effective_interval(self):
        engagement = self._engagement(
            status=ExternalEngagementStatus.ENDED,
            end_at=date(2026, 9, 1),
        )

        result = self._provide(as_of=date(2026, 8, 1))

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual([item.source_object_id for item in result.items], [str(engagement.id)])
        self.assertEqual(result.items[0].verification_status, "VERIFIED")
        self.assertEqual(result.items[0].snapshot_json["effectiveStatus"], "ACTIVE")
        self.assertEqual(result.items[0].snapshot_json["sourceCurrentStatus"], "ENDED")
        self.assertEqual(result.source_updated_at, engagement.updated_at)

    def test_terminal_state_without_end_boundary_is_partial_not_fake_active(self):
        engagement = self._engagement(status=ExternalEngagementStatus.ENDED)

        result = self._provide()

        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertEqual(result.items, [])
        self.assertIn(str(engagement.id), result.errors[0].message)

    def test_cross_tenant_category_reference_fails_closed(self):
        foreign_category = HrExternalCategory.objects.create(
            tenant_id=99999,
            code=f"FOREIGN-{uuid.uuid4().hex[:8]}",
            name="Foreign Tenant Category",
        )
        self._engagement(
            status=ExternalEngagementStatus.ACTIVE,
            category=foreign_category,
        )

        result = self._provide()

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "CATEGORY_TENANT_MISMATCH")
