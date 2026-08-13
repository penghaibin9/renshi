import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_data import api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr18DefinitionApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("hr_data.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_data.api.get_allowed_company_ids", return_value={7})
    def test_view_permission_alone_cannot_author_definitions(self, _allowed, _tenant):
        request = self.factory.post(
            "/api/v1/hr/data/definitions/populations/",
            data=json.dumps(
                {
                    "populationCode": "ACTIVE_STAFF",
                    "name": "在职教职工",
                    "rootDomain": "HR03",
                    "predicate": {"field": "employment.status", "op": "eq", "value": "ACTIVE"},
                    "sourceDomains": ["HR03"],
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.READ_PERMISSION})

        response = api.create_population_definition(request)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(api.DEFINE_PERMISSION.encode(), response.content)

    @patch("hr_data.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_data.api.get_allowed_company_ids", return_value={7})
    @patch("hr_data.api.HrDataDefinitionService")
    def test_population_api_uses_resolved_tenant_and_actor(
        self, service_cls, _allowed, _tenant
    ):
        definition = SimpleNamespace(
            id=uuid.uuid4(),
            population_code="ACTIVE_STAFF",
            version_no=1,
            status="DRAFT",
            content_hash="a" * 64,
        )
        service_cls.return_value.create_population_version.return_value = SimpleNamespace(
            definition=definition,
            created=True,
        )
        request = self.factory.post(
            "/api/v1/hr/data/definitions/populations/",
            data=json.dumps(
                {
                    "populationCode": "ACTIVE_STAFF",
                    "name": "在职教职工",
                    "rootDomain": "HR03",
                    "predicate": {"field": "employment.status", "op": "eq", "value": "ACTIVE"},
                    "sourceDomains": ["HR03"],
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.DEFINE_PERMISSION})

        response = api.create_population_definition(request)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        self.assertIn(b'"populationCode": "ACTIVE_STAFF"', response.content)
        self.assertIn(b'"schemaVersion": "hr18.population-definition.1"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_data.api.get_allowed_company_ids", return_value={7})
    @patch("hr_data.api.HrDataDefinitionService")
    def test_dimension_api_returns_200_for_identical_version_replay(
        self, service_cls, _allowed, _tenant
    ):
        definition = SimpleNamespace(
            id=uuid.uuid4(),
            dimension_code="DEPARTMENT",
            version_no=2,
            status="DRAFT",
            content_hash="b" * 64,
        )
        service_cls.return_value.create_dimension_version.return_value = SimpleNamespace(
            definition=definition,
            created=False,
        )
        request = self.factory.post(
            "/api/v1/hr/data/definitions/dimensions/",
            data=json.dumps(
                {
                    "dimensionCode": "DEPARTMENT",
                    "name": "部门",
                    "sourceDomain": "HR02",
                    "attributePath": "organization.department_code",
                    "valueType": "CODE",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({api.DEFINE_PERMISSION})

        response = api.create_dimension_definition(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"created": false', response.content)

    def test_non_post_is_rejected(self):
        request = self.factory.get("/api/v1/hr/data/definitions/populations/")
        request.user = UserStub({api.DEFINE_PERMISSION})
        response = api.create_population_definition(request)
        self.assertEqual(response.status_code, 405)
