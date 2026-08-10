from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_external.services.engagement_service import (
    CrossTenantReference,
    EngagementCreateInput,
    EngagementOverlap,
    EngagementService,
)


class EngagementConcurrencyAndOverlapTests(SimpleTestCase):
    @patch("hr_external.services.engagement_service.HrExternalEngagement.objects")
    @patch("hr_external.services.engagement_service.HrExternalCategory.objects")
    @patch("hr_external.services.engagement_service.HrExternalTeacherProfile.objects")
    def test_profile_lock_is_tenant_scoped_before_overlap_check(
        self,
        profile_objects,
        category_objects,
        engagement_objects,
    ):
        profile = SimpleNamespace(person_id_id="person-1", tenant_id=77)
        profile_objects.select_for_update.return_value.select_related.return_value.get.return_value = profile
        category = SimpleNamespace(tenant_id=77, agreement_requirement="REQUIRED_BEFORE_ACTIVATION")
        category_objects.get.return_value = category
        overlap = MagicMock()
        overlap.filter.return_value = overlap
        overlap.exists.return_value = False
        engagement_objects.filter.return_value = overlap
        created = MagicMock()
        engagement_objects.create.return_value = created

        payload = EngagementCreateInput(
            tenant_id=77,
            person_id="person-1",
            profile_id=5,
            category_id=6,
            host_organization_id=9,
            start_at=date(2026, 9, 1),
            end_at=date(2026, 10, 1),
        )
        result = EngagementService().create_engagement(payload)

        profile_objects.select_for_update.return_value.select_related.return_value.get.assert_called_once_with(
            id=5,
            tenant_id=77,
        )
        category_objects.get.assert_called_once_with(id=6, tenant_id=77)
        self.assertIs(result, created)

    @patch("hr_external.services.engagement_service.HrExternalEngagement.objects")
    @patch("hr_external.services.engagement_service.HrExternalCategory.objects")
    @patch("hr_external.services.engagement_service.HrExternalTeacherProfile.objects")
    def test_half_open_adjacent_interval_is_not_forced_to_overlap(
        self,
        profile_objects,
        category_objects,
        engagement_objects,
    ):
        profile_objects.select_for_update.return_value.select_related.return_value.get.return_value = SimpleNamespace(
            person_id_id="person-1", tenant_id=77
        )
        category_objects.get.return_value = SimpleNamespace(
            tenant_id=77,
            agreement_requirement="REQUIRED_BEFORE_ACTIVATION",
        )
        base_qs = MagicMock()
        after_end_filter_qs = MagicMock()
        final_qs = MagicMock()
        final_qs.exists.return_value = False
        engagement_objects.filter.return_value = base_qs
        base_qs.filter.return_value = after_end_filter_qs
        after_end_filter_qs.filter.return_value = final_qs
        engagement_objects.create.return_value = MagicMock()

        payload = EngagementCreateInput(
            tenant_id=77,
            person_id="person-1",
            profile_id=5,
            category_id=6,
            host_organization_id=9,
            start_at=date(2026, 9, 1),
            end_at=date(2026, 10, 1),
        )
        EngagementService().create_engagement(payload)

        # 关键断言：半开区间要求 existing.end > new.start，而不是 >=；
        # 再要求 existing.start < new.end，因此边界相接可并存。
        self.assertEqual(base_qs.filter.call_count, 1)
        after_end_filter_qs.filter.assert_called_once_with(start_at__lt=date(2026, 10, 1))

    def test_agreement_projection_rejects_cross_tenant_engagement(self):
        engagement = SimpleNamespace(tenant_id=88)
        with self.assertRaises(CrossTenantReference):
            EngagementService().set_agreement_status(
                engagement,
                "SIGNED",
                tenant_id=77,
            )
