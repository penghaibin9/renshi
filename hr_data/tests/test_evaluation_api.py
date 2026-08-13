import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import evaluation_api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class HistoricalEvaluationApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _result(*, kind="METRIC", code="HEADCOUNT", grain="STAFF"):
        evidence = SimpleNamespace(
            id=uuid.uuid4(),
            evidence_no="EV-001",
            evidence_hash="a" * 64,
        )
        return SimpleNamespace(
            definition_kind=kind,
            definition_code=code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            population_code="ACTIVE_STAFF",
            population_version=1,
            grain=grain,
            value=123,
            evidence=evidence,
            calculation_hash="b" * 64,
        )

    @patch("hr_data.evaluation_api.HistoricalEvaluationRouter")
    @patch("hr_data.evaluation_api.resolve_request_tenant", return_value=77)
    def test_metric_count_evaluation_uses_asof_permission_and_router(
        self, tenant_resolver, router_cls
    ):
        router_cls.return_value.evaluate_count_metric.return_value = SimpleNamespace(
            result=self._result(),
            evaluator_version="hr13-title-person-count-v1",
        )
        request = self.factory.post(
            "/api/v1/hr/data/as-of/evaluate/",
            data=json.dumps(
                {
                    "evidenceNo": "EV-001",
                    "definitionKind": "METRIC",
                    "definitionCode": "HEADCOUNT",
                    "definitionVersion": 1,
                    "asOfDate": "2026-08-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = evaluation_api.evaluate(request)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=evaluation_api.ASOF_PERMISSION,
        )
        router_cls.assert_called_once_with(77, actor_user_id=88)
        kwargs = router_cls.return_value.evaluate_count_metric.call_args.kwargs
        self.assertEqual(kwargs["metric_code"], "HEADCOUNT")
        self.assertEqual(kwargs["metric_version"], 1)
        self.assertEqual(kwargs["as_of_date"], date(2026, 8, 1))
        self.assertIn(b'"value": 123', response.content)
        self.assertIn(b'"grain": "STAFF"', response.content)
        self.assertIn(b'"evaluatorVersion": "hr13-title-person-count-v1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.evaluation_api.HistoricalEvaluationRouter")
    @patch("hr_data.evaluation_api.resolve_request_tenant", return_value=77)
    def test_population_evaluation_routes_to_population_method(self, _tenant, router_cls):
        router_cls.return_value.evaluate_population.return_value = SimpleNamespace(
            result=self._result(kind="POPULATION", code="ACTIVE_STAFF", grain="ASSIGNMENT"),
            evaluator_version="hr03-assignment-count-v1",
        )
        request = self.factory.post(
            "/api/v1/hr/data/as-of/evaluate/",
            data=json.dumps(
                {
                    "evidenceNo": "EV-001",
                    "definitionKind": "POPULATION",
                    "definitionCode": "ACTIVE_STAFF",
                    "definitionVersion": 1,
                    "asOfDate": "2026-08-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = evaluation_api.evaluate(request)

        self.assertEqual(response.status_code, 200)
        router_cls.return_value.evaluate_population.assert_called_once_with(
            evidence_no="EV-001",
            population_code="ACTIVE_STAFF",
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )
        router_cls.return_value.evaluate_count_metric.assert_not_called()
        self.assertIn(b'"evaluatorVersion": "hr03-assignment-count-v1"', response.content)

    @patch("hr_data.evaluation_api.HistoricalEvaluationRouter")
    @patch("hr_data.evaluation_api.resolve_request_tenant", return_value=77)
    def test_invalid_version_or_date_never_calls_evaluator(self, _tenant, router_cls):
        for payload in (
            {
                "evidenceNo": "EV-001",
                "definitionKind": "METRIC",
                "definitionCode": "HEADCOUNT",
                "definitionVersion": "bad",
                "asOfDate": "2026-08-01",
            },
            {
                "evidenceNo": "EV-001",
                "definitionKind": "METRIC",
                "definitionCode": "HEADCOUNT",
                "definitionVersion": 1,
                "asOfDate": "bad-date",
            },
        ):
            request = self.factory.post(
                "/api/v1/hr/data/as-of/evaluate/",
                data=json.dumps(payload),
                content_type="application/json",
            )
            request.user = UserStub()
            response = evaluation_api.evaluate(request)
            self.assertEqual(response.status_code, 400)
        router_cls.assert_not_called()

    @patch("hr_data.evaluation_api.HistoricalEvaluationRouter")
    @patch("hr_data.evaluation_api.resolve_request_tenant", return_value=77)
    def test_evidence_stale_and_missing_integrated_source_map_to_conflict(
        self, _tenant, router_cls
    ):
        from hr_data.services.evaluation_service import AsOfEvaluationError

        for code in (
            "ASOF_EVALUATION_EVIDENCE_STALE",
            "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
        ):
            router_cls.return_value.evaluate_count_metric.side_effect = AsOfEvaluationError(
                code,
                "cannot produce a formal value",
            )
            request = self.factory.post(
                "/api/v1/hr/data/as-of/evaluate/",
                data=json.dumps(
                    {
                        "evidenceNo": "EV-OLD",
                        "definitionKind": "METRIC",
                        "definitionCode": "HEADCOUNT",
                        "definitionVersion": 1,
                        "asOfDate": "2026-08-01",
                    }
                ),
                content_type="application/json",
            )
            request.user = UserStub()

            response = evaluation_api.evaluate(request)

            self.assertEqual(response.status_code, 409)
            self.assertIn(code.encode(), response.content)
            router_cls.return_value.evaluate_count_metric.reset_mock(side_effect=True)
