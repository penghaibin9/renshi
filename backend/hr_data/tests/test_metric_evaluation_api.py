import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import metric_evaluation_api
from hr_data.services.metric_expression_service import MetricExpressionError


class UserStub:
    id = 91
    is_authenticated = True
    is_superuser = False


class MetricEvaluationApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.evidence_id = uuid.uuid4()
        self.snapshot_id = uuid.uuid4()

    @patch("hr_data.metric_evaluation_api.MetricExpressionEvaluationService")
    @patch("hr_data.metric_evaluation_api.resolve_request_tenant", return_value=77)
    def test_api_enforces_dedicated_permission_and_typed_identity(
        self, tenant_resolver, service_cls
    ):
        snapshot = SimpleNamespace(
            id=self.snapshot_id,
            evaluation_no="EVAL-001",
            metric_code="HEADCOUNT",
            metric_version=2,
            population_code="ACTIVE_STAFF",
            population_version=3,
            dimension_versions_json=[{"code": "STATUS", "version": 1}],
            as_of_date=date(2026, 8, 1),
            as_of_evidence_id=self.evidence_id,
            evidence_hash="a" * 64,
            result_json={"kind": "SCALAR", "value": 10},
            input_row_count=10,
            provider_version="provider-v1",
            evaluator_version="engine-v1",
            calculation_hash="b" * 64,
        )
        service_cls.return_value.evaluate.return_value = SimpleNamespace(
            snapshot=snapshot,
            created=True,
        )
        request = self.factory.post(
            "/api/v1/hr/data/metrics/evaluate/",
            data=json.dumps(
                {
                    "evaluationNo": "EVAL-001",
                    "metricCode": "HEADCOUNT",
                    "metricVersion": 2,
                    "asOfDate": "2026-08-01",
                    "evidenceId": str(self.evidence_id),
                    "dimensions": [{"code": "STATUS", "version": 1}],
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = metric_evaluation_api.evaluate_metric(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=metric_evaluation_api.METRIC_EVALUATE_PERMISSION,
        )
        service_cls.assert_called_once_with(77, actor_user_id=91)
        kwargs = service_cls.return_value.evaluate.call_args.kwargs
        self.assertEqual(kwargs["evidence_id"], self.evidence_id)
        self.assertEqual(kwargs["metric_version"], 2)

    @patch("hr_data.metric_evaluation_api.MetricExpressionEvaluationService")
    @patch("hr_data.metric_evaluation_api.resolve_request_tenant", return_value=77)
    def test_stale_evidence_maps_to_conflict(self, _tenant, service_cls):
        service_cls.return_value.evaluate.side_effect = MetricExpressionError(
            "HR18_METRIC_EVIDENCE_STALE", "stale"
        )
        request = self.factory.post(
            "/api/v1/hr/data/metrics/evaluate/",
            data=json.dumps(
                {
                    "evaluationNo": "EVAL-001",
                    "metricCode": "HEADCOUNT",
                    "metricVersion": 2,
                    "asOfDate": "2026-08-01",
                    "evidenceId": str(self.evidence_id),
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        response = metric_evaluation_api.evaluate_metric(request)
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"HR18_METRIC_EVIDENCE_STALE", response.content)

    def test_bad_evidence_uuid_and_non_post_are_rejected(self):
        request = self.factory.post(
            "/api/v1/hr/data/metrics/evaluate/",
            data=json.dumps(
                {
                    "asOfDate": "2026-08-01",
                    "evidenceId": "not-a-uuid",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()
        with patch(
            "hr_data.metric_evaluation_api.resolve_request_tenant", return_value=77
        ):
            response = metric_evaluation_api.evaluate_metric(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"HR18_METRIC_EVIDENCE_ID_INVALID", response.content)

        get_request = self.factory.get("/api/v1/hr/data/metrics/evaluate/")
        get_request.user = UserStub()
        self.assertEqual(metric_evaluation_api.evaluate_metric(get_request).status_code, 405)
