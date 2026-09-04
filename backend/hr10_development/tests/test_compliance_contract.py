import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr10_development.api.development_records import get_compliance
from hr10_development.constants import VerificationStatus
from hr10_development.services.compliance_service import ComplianceService


class _FakeFactQuery:
    def __init__(self, facts):
        self.facts = facts
        self.filters = []

    def effective(self):
        return self

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def __getitem__(self, item):
        return self.facts[item]


class ComplianceServiceContractTests(SimpleTestCase):
    def test_compliance_applies_as_of_activity_and_trust_filters(self):
        query = _FakeFactQuery(
            [SimpleNamespace(verified_days=10, verified_hours=None)]
        )
        rule = SimpleNamespace(
            time_window_type="CALENDAR_YEAR",
            unit="DAYS",
            eligible_activity_types=["ENTERPRISE_PRACTICE"],
            minimum_trust_level=4,
        )

        with patch(
            "hr10_development.models.development_fact.HrDevelopmentFact.objects",
            query,
        ):
            value = ComplianceService._compute_current_value(
                staff_master_id=18,
                tenant_id=7,
                rule=rule,
                as_of=__import__("datetime").date(2026, 9, 2),
            )

        self.assertEqual(value, 10)
        keyword_filters = [kwargs for _args, kwargs in query.filters]
        self.assertIn("valid_from__lte", keyword_filters[0])
        self.assertIn(
            {"activity_type__in": ("ENTERPRISE_PRACTICE",)}, keyword_filters
        )
        trust_filter = next(
            item["verification_status__in"]
            for item in keyword_filters
            if "verification_status__in" in item
        )
        self.assertIn(VerificationStatus.HR_VERIFIED, trust_filter)
        self.assertNotIn(VerificationStatus.DOCUMENT_VERIFIED, trust_filter)


class ComplianceApiValidationTests(SimpleTestCase):
    def _request(self, query=""):
        request = RequestFactory().get(
            f"/api/v1/hr/development/development-records/18/compliance{query}"
        )
        request.tenant_id = 7
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        return request

    @patch("hr10_development.api.development_records.ComplianceService")
    def test_invalid_staff_or_date_returns_400_without_running_engine(self, service):
        invalid_staff = get_compliance(self._request(), "not-a-number")
        invalid_date = get_compliance(self._request("?asOf=2026-02-30"), "18")

        self.assertEqual(invalid_staff.status_code, 400)
        self.assertEqual(invalid_date.status_code, 400)
        self.assertEqual(
            json.loads(invalid_date.content)["error"]["code"], "INVALID_REQUEST"
        )
        service.evaluate_compliance.assert_not_called()

