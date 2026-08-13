import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import quality_api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class QualityApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _rule():
        return SimpleNamespace(
            id=uuid.uuid4(),
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            version_no=2,
            name="在职关系结束日期完整性",
            source_domain="HR03",
            severity="ERROR",
            parameters_json={"statuses": ["ACTIVE"]},
            as_of_required=True,
            status="DRAFT",
            content_hash="a" * 64,
        )

    @staticmethod
    def _run(*, status="SUCCESS", findings=()):
        run = SimpleNamespace(
            id=uuid.uuid4(),
            run_no="QRUN-001",
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            rule_version=2,
            source_domain="HR03",
            as_of_date=date(2026, 8, 1),
            status=status,
            provider_version="hr03-v4" if status not in {"UNAVAILABLE", "ERROR"} else "",
            evidence_hash="b" * 64 if status not in {"UNAVAILABLE", "ERROR"} else "",
            finding_count=len(findings),
            error_message=("provider unavailable" if status == "UNAVAILABLE" else ""),
            executed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
        return SimpleNamespace(run=run, findings=tuple(findings), created=True)

    @staticmethod
    def _finding():
        return SimpleNamespace(
            id=uuid.uuid4(),
            finding_no="DQ-001",
            quality_run_id=uuid.uuid4(),
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            rule_version=2,
            source_domain="HR03",
            source_object_ref="employment:1001",
            finding_fingerprint="c" * 64,
            severity="ERROR",
            details_json={"reason": "missing"},
            status="OPEN",
            detected_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
            resolved_at=None,
        )

    @patch("hr_data.quality_api.DataQualityRuleService")
    @patch("hr_data.quality_api.resolve_request_tenant", return_value=77)
    def test_create_rule_uses_dedicated_quality_permission(self, tenant_resolver, service_cls):
        service_cls.return_value.create_rule_version.return_value = SimpleNamespace(
            rule=self._rule(), created=True
        )
        request = self.factory.post(
            "/api/v1/hr/data/quality/rules/",
            data=json.dumps(
                {
                    "ruleCode": "EMPLOYMENT_END_DATE_REQUIRED",
                    "name": "在职关系结束日期完整性",
                    "sourceDomain": "HR03",
                    "severity": "ERROR",
                    "parameters": {"statuses": ["ACTIVE"]},
                    "asOfRequired": True,
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = quality_api.create_rule(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=quality_api.QUALITY_PERMISSION,
        )
        kwargs = service_cls.return_value.create_rule_version.call_args.kwargs
        self.assertEqual(kwargs["source_domain"], "HR03")
        self.assertEqual(kwargs["parameters"], {"statuses": ["ACTIVE"]})
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.quality_api.DataQualityExecutionService")
    @patch("hr_data.quality_api.resolve_request_tenant", return_value=77)
    def test_execute_parses_asof_date_and_returns_real_findings(self, tenant_resolver, service_cls):
        finding = self._finding()
        service_cls.return_value.execute.return_value = self._run(findings=(finding,))
        request = self.factory.post(
            "/api/v1/hr/data/quality/runs/",
            data=json.dumps(
                {
                    "runNo": "QRUN-001",
                    "ruleCode": "EMPLOYMENT_END_DATE_REQUIRED",
                    "ruleVersion": 2,
                    "asOfDate": "2026-08-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = quality_api.execute_run(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=quality_api.QUALITY_PERMISSION,
        )
        kwargs = service_cls.return_value.execute.call_args.kwargs
        self.assertEqual(kwargs["as_of_date"], date(2026, 8, 1))
        self.assertIn(b'"findingCount": 1', response.content)
        self.assertIn(b'"sourceObjectRef": "employment:1001"', response.content)

    @patch("hr_data.quality_api.DataQualityExecutionService")
    @patch("hr_data.quality_api.resolve_request_tenant", return_value=77)
    def test_invalid_asof_date_does_not_call_provider_execution(self, _tenant, service_cls):
        request = self.factory.post(
            "/api/v1/hr/data/quality/runs/",
            data=json.dumps(
                {
                    "runNo": "QRUN-001",
                    "ruleCode": "EMPLOYMENT_END_DATE_REQUIRED",
                    "ruleVersion": 2,
                    "asOfDate": "not-a-date",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        response = quality_api.execute_run(request)
        self.assertEqual(response.status_code, 400)
        service_cls.assert_not_called()

    @patch("hr_data.quality_api.DataQualityExecutionService")
    @patch("hr_data.quality_api.resolve_request_tenant", return_value=77)
    def test_unavailable_run_is_not_presented_as_success(self, _tenant, service_cls):
        service_cls.return_value.execute.return_value = self._run(status="UNAVAILABLE")
        request = self.factory.post(
            "/api/v1/hr/data/quality/runs/",
            data=json.dumps(
                {
                    "runNo": "QRUN-UNAVAILABLE",
                    "ruleCode": "EMPLOYMENT_END_DATE_REQUIRED",
                    "ruleVersion": 2,
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        response = quality_api.execute_run(request)
        self.assertEqual(response.status_code, 201)
        self.assertIn(b'"status": "UNAVAILABLE"', response.content)
        self.assertNotIn(b'"status": "SUCCESS"', response.content)
        self.assertIn(b'"provider unavailable"', response.content)
