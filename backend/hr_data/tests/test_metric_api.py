import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import metric_api
from hr_data.services.definition_service import HrDataDefinitionError


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class HrMetricDefinitionApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.definition_id = uuid.uuid4()

    @patch("hr_data.metric_api.HrMetricDefinitionService")
    @patch("hr_data.metric_api.resolve_request_tenant", return_value=77)
    def test_create_metric_uses_define_permission_and_typed_payload(
        self, tenant_resolver, service_cls
    ):
        definition = SimpleNamespace(
            id=self.definition_id,
            metric_code="ACTIVE_STAFF_COUNT",
            version_no=1,
            status="DRAFT",
            content_hash="a" * 64,
            population_code="ACTIVE_STAFF",
            expression='{"dslVersion":"1","field":null,"op":"COUNT","populationVersion":1}',
        )
        service_cls.return_value.create_metric_version.return_value = SimpleNamespace(
            definition=definition,
            created=True,
        )
        request = self.factory.post(
            "/api/v1/hr/data/definitions/metrics/",
            data=json.dumps(
                {
                    "metricCode": "ACTIVE_STAFF_COUNT",
                    "name": "在职教职工人数",
                    "valueType": "INTEGER",
                    "unit": "人",
                    "populationCode": "ACTIVE_STAFF",
                    "populationVersion": 1,
                    "expression": {"op": "COUNT"},
                    "sourceDomains": ["HR03"],
                    "asOfRequired": True,
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = metric_api.create_metric_definition(request)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request, required_permission=metric_api.DEFINE_PERMISSION
        )
        service_cls.assert_called_once_with(77, actor_user_id=88)
        kwargs = service_cls.return_value.create_metric_version.call_args.kwargs
        self.assertEqual(kwargs["metric_code"], "ACTIVE_STAFF_COUNT")
        self.assertEqual(kwargs["population_version"], 1)
        self.assertEqual(kwargs["expression"], {"op": "COUNT"})
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.metric_api.HrMetricDefinitionService")
    @patch("hr_data.metric_api.resolve_request_tenant", return_value=77)
    def test_missing_population_version_maps_to_404(
        self, _tenant, service_cls
    ):
        service_cls.return_value.create_metric_version.side_effect = HrDataDefinitionError(
            "HR18_POPULATION_VERSION_NOT_FOUND",
            "population missing",
        )
        request = self.factory.post(
            "/api/v1/hr/data/definitions/metrics/",
            data=json.dumps(
                {
                    "metricCode": "COUNT_X",
                    "name": "X",
                    "valueType": "INTEGER",
                    "populationCode": "MISSING",
                    "populationVersion": 1,
                    "expression": {"op": "COUNT"},
                    "sourceDomains": ["HR03"],
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = metric_api.create_metric_definition(request)

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"HR18_POPULATION_VERSION_NOT_FOUND", response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get("/api/v1/hr/data/definitions/metrics/")
        request.user = UserStub()
        response = metric_api.create_metric_definition(request)
        self.assertEqual(response.status_code, 405)
