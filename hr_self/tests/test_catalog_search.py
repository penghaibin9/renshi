import uuid

from django.test import RequestFactory, TestCase

from hr_self import catalog_api
from hr_self.models import SelfServiceCatalogItem, SelfServicePinnedService
from hr_self.services.catalog_service import SelfCatalogError, SelfCatalogService
from hr_self.services.identity_service import SelfIdentityContext


class SelfCatalogSearchTests(TestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id=uuid.uuid4(),
            person_id=uuid.uuid4(),
            legacy_employee_id=55,
        )
        self.service = SelfCatalogService(self.context)

    def _item(
        self,
        code,
        name,
        *,
        tenant_id=77,
        domain="HR07",
        action="OPEN",
        keywords="",
        enabled=True,
        sort_order=100,
    ):
        return SelfServiceCatalogItem.objects.create(
            tenant_id=tenant_id,
            service_code=code,
            name=name,
            source_domain=domain,
            action_key=action,
            route=f"/self/{code.lower()}/",
            audience="SELF",
            enabled=enabled,
            sort_order=sort_order,
            search_keywords=keywords,
        )

    def test_search_is_tenant_bound_and_matches_dedicated_keywords(self):
        target = self._item(
            "CONTRACT_QUERY",
            "合同查询",
            domain="HR07",
            keywords="续签 到期 聘用",
            sort_order=10,
        )
        self._item(
            "FOREIGN_CONTRACT",
            "外校合同",
            tenant_id=88,
            domain="HR07",
            keywords="续签",
        )
        self._item(
            "DISABLED",
            "停用服务",
            keywords="续签",
            enabled=False,
        )
        SelfServicePinnedService.objects.create(
            tenant_id=77,
            staff_id=self.context.staff_id,
            service_code=target.service_code,
            sort_order=1,
        )

        result = self.service.search(query="续签")

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["service_code"], "CONTRACT_QUERY")
        self.assertTrue(result["items"][0]["pinned"])

    def test_source_domain_filter_and_pagination_are_stable(self):
        self._item("A", "A服务", domain="HR07", sort_order=1)
        self._item("B", "B服务", domain="HR07", sort_order=2)
        self._item("C", "C服务", domain="HR15", sort_order=3)

        result = self.service.search(source_domain="hr07", limit=1, offset=1)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["limit"], 1)
        self.assertEqual(result["offset"], 1)
        self.assertEqual(result["sourceDomain"], "HR07")
        self.assertEqual([item["service_code"] for item in result["items"]], ["B"])

    def test_invalid_pagination_fails_closed(self):
        for limit, offset in ((0, 0), (101, 0), (24, -1)):
            with self.assertRaises(SelfCatalogError) as ctx:
                self.service.search(limit=limit, offset=offset)
            self.assertEqual(ctx.exception.code, "SELF_SERVICE_PAGINATION_INVALID")


class SelfCatalogApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id=uuid.uuid4(),
            person_id=uuid.uuid4(),
            legacy_employee_id=55,
        )
        SelfServiceCatalogItem.objects.create(
            tenant_id=77,
            service_code="PAYSLIP",
            name="工资条",
            source_domain="HR15",
            action_key="VIEW_PAYSLIP",
            route="/self/payslip/",
            enabled=True,
            sort_order=1,
            search_keywords="薪资 工资",
        )

    def test_api_uses_resolved_self_context_and_returns_search_result(self):
        request = self.factory.get(
            "/api/v1/hr/self/services/?q=薪资&sourceDomain=HR15&limit=10&offset=0"
        )
        request.user = object()

        original = catalog_api.resolve_self_context
        catalog_api.resolve_self_context = lambda _request: self.context
        try:
            response = catalog_api.service_catalog(request)
        finally:
            catalog_api.resolve_self_context = original

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"PAYSLIP", response.content)
        self.assertIn(b'"total": 1', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_api_rejects_invalid_pagination(self):
        request = self.factory.get("/api/v1/hr/self/services/?limit=oops")
        request.user = object()

        original = catalog_api.resolve_self_context
        catalog_api.resolve_self_context = lambda _request: self.context
        try:
            response = catalog_api.service_catalog(request)
        finally:
            catalog_api.resolve_self_context = original

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"SELF_SERVICE_PAGINATION_INVALID", response.content)
