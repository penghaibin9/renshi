import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from hr10_development.api.internal import (
    get_development_time_windows,
    get_hr09_evidence,
)
from hr10_development.providers.base import ProviderResult, ProviderStatus


SERVICE_SETTINGS = {
    "HR09": "hr09-test-secret",
    "HR11": "hr11-test-secret",
}


def _request(path, *, caller, token):
    request = RequestFactory().get(
        path,
        headers={
            "X-HR10-Caller": caller,
            "X-HR10-Service-Token": token,
        },
    )
    request.tenant_id = 7
    return request


@override_settings(HR10_INTERNAL_SERVICE_CREDENTIALS=SERVICE_SETTINGS)
class InternalProviderApiContractTests(SimpleTestCase):
    @patch("hr10_development.api.internal.Hr09QualificationEvidenceProvider")
    def test_hr09_evidence_returns_valid_meta_instead_of_crashing(self, provider_type):
        provider_type.return_value.get_evidence.return_value = ProviderResult(
            status=ProviderStatus.OK,
            data=[{"sourceFactId": "fact-1"}],
            source_updated_at=datetime(2026, 9, 2, 8, 30, tzinfo=timezone.utc),
        )
        request = _request(
            "/internal/hr/development/evidence/staff/18"
            "?asOf=2026-09-01&types=TRAINING_COMPLETION,ENTERPRISE_PRACTICE",
            caller="HR09",
            token="hr09-test-secret",
        )

        response = get_hr09_evidence(request, "18")
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["meta"]["dataFreshness"], "FRESH")
        self.assertEqual(payload["meta"]["sourceUpdatedAt"], "2026-09-02T08:30:00+00:00")
        provider_type.return_value.get_evidence.assert_called_once()

    @patch("hr10_development.api.internal.Hr09QualificationEvidenceProvider")
    def test_hr09_evidence_rejects_invalid_dates_and_fact_types(self, provider_type):
        invalid_date = _request(
            "/internal/hr/development/evidence/staff/18?asOf=2026-02-30",
            caller="HR09",
            token="hr09-test-secret",
        )
        invalid_type = _request(
            "/internal/hr/development/evidence/staff/18?types=UNKNOWN_FACT",
            caller="HR09",
            token="hr09-test-secret",
        )

        self.assertEqual(get_hr09_evidence(invalid_date, "18").status_code, 400)
        self.assertEqual(get_hr09_evidence(invalid_type, "18").status_code, 400)
        provider_type.return_value.get_evidence.assert_not_called()

    @patch("hr10_development.providers.time_provider.Hr11DevelopmentTimeProvider")
    def test_hr11_windows_require_a_bounded_valid_period(self, provider_type):
        missing = _request(
            "/internal/hr/development/time-windows/staff/18",
            caller="HR11",
            token="hr11-test-secret",
        )
        inverted = _request(
            "/internal/hr/development/time-windows/staff/18"
            "?periodStart=2026-09-02&periodEnd=2026-09-01",
            caller="HR11",
            token="hr11-test-secret",
        )
        oversized = _request(
            "/internal/hr/development/time-windows/staff/18"
            "?periodStart=2025-01-01&periodEnd=2026-09-01",
            caller="HR11",
            token="hr11-test-secret",
        )

        self.assertEqual(get_development_time_windows(missing, "18").status_code, 400)
        self.assertEqual(get_development_time_windows(inverted, "18").status_code, 400)
        self.assertEqual(get_development_time_windows(oversized, "18").status_code, 400)
        provider_type.return_value.get_development_time_windows.assert_not_called()

    @patch("hr10_development.providers.time_provider.Hr11DevelopmentTimeProvider")
    def test_hr11_windows_pass_the_requested_period_to_provider(self, provider_type):
        provider_type.return_value.get_development_time_windows.return_value = ProviderResult(
            status=ProviderStatus.OK,
            data=[],
        )
        request = _request(
            "/internal/hr/development/time-windows/staff/18"
            "?periodStart=2026-09-01&periodEnd=2026-09-30",
            caller="HR11",
            token="hr11-test-secret",
        )

        response = get_development_time_windows(request, "18")

        self.assertEqual(response.status_code, 200)
        provider_type.return_value.get_development_time_windows.assert_called_once()
