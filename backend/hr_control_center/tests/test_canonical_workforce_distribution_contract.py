from datetime import date, datetime, timezone

from django.test import SimpleTestCase

from hr_control_center.context import HrRequestContext, HrScope
from hr_control_center.providers.base import (
    AUTHORITY_ONLY,
    DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
    DUAL_READ_COMPARE,
    LEGACY_ONLY,
)
from hr_control_center.providers.canonical_workforce import (
    CanonicalWorkforceMetricProvider,
)
from hr_control_center.providers.workforce import LegacyWorkforceProvider
from hr_control_center.services.workforce_service import WorkforceService


class CanonicalWorkforceDistributionContractTests(SimpleTestCase):
    def _context(self, authority_mode=AUTHORITY_ONLY, as_of=date(2026, 9, 2)):
        return HrRequestContext(
            tenant_id=7,
            authority_mode=authority_mode,
            as_of=as_of,
            scope=HrScope("SCHOOL"),
            request_snapshot_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc),
        )

    def test_canonical_provider_implements_complete_workforce_protocol(self):
        provider = CanonicalWorkforceMetricProvider()
        for method_name in (
            "active_headcount",
            "distribution_by_employee_type",
            "distribution_by_department",
            "distribution_by_hr02_org",
            "distribution_by_job_position",
            "distribution_by_gender",
            "distribution_by_age_group",
            "org_comparison",
        ):
            self.assertTrue(callable(getattr(provider, method_name)))

    def test_chinese_labels_and_full_year_age_are_stable(self):
        provider = CanonicalWorkforceMetricProvider()
        self.assertEqual(provider._STAFF_CATEGORY_LABELS["TEACHER"], "教师")
        self.assertEqual(provider._GENDER_LABELS["F"], "女")
        self.assertEqual(provider._age_on(date(1990, 9, 3), date(2026, 9, 2)), 35)
        self.assertEqual(provider._age_bucket(35), ("AGE_31_35", "31-35"))

    def test_incomplete_org_scope_fails_closed_without_querying(self):
        provider = CanonicalWorkforceMetricProvider()
        context = HrRequestContext(
            tenant_id=7,
            authority_mode=AUTHORITY_ONLY,
            scope=HrScope("COLLEGE"),
            request_snapshot_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc),
        )
        result = provider.distribution_by_department(context)
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertEqual(result.reason_code, "AUTHORITY_SCOPE_NOT_SUPPORTED")

    def test_service_routes_dual_and_authority_modes_to_canonical_provider(self):
        service = WorkforceService()
        self.assertIsInstance(
            service._provider_for(self._context(AUTHORITY_ONLY)),
            CanonicalWorkforceMetricProvider,
        )
        self.assertIsInstance(
            service._provider_for(self._context(DUAL_READ_COMPARE)),
            CanonicalWorkforceMetricProvider,
        )
        self.assertIsInstance(
            service._provider_for(self._context(LEGACY_ONLY)),
            LegacyWorkforceProvider,
        )

    def test_historical_query_is_blocked_only_for_legacy_snapshot(self):
        service = WorkforceService()
        historical = self._context(LEGACY_ONLY, as_of=date(2025, 9, 2))
        legacy_gate = service._gates(historical, "workforce_summary", service.provider)
        self.assertEqual(legacy_gate["reasonCode"], "AS_OF_NOT_CURRENT")

        authority = self._context(AUTHORITY_ONLY, as_of=date(2025, 9, 2))
        self.assertIsNone(
            service._gates(authority, "workforce_summary", service.canonical_provider)
        )
        unavailable = service._unavailable_contract(
            authority,
            "workforce_summary",
            reason_code="AUTHORITY_DATA_NOT_INITIALIZED",
            message="未初始化",
        )
        self.assertEqual(
            unavailable["dataBasis"], DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT
        )
