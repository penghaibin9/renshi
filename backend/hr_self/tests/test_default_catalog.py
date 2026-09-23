import uuid

from django.test import TestCase

from hr_self.models import SelfServiceCatalogItem
from hr_self.services.catalog_service import SelfCatalogService
from hr_self.services.default_catalog import DEFAULT_SELF_SERVICES, ensure_default_catalog_if_empty
from hr_self.services.identity_service import SelfIdentityContext


class DefaultSelfCatalogTests(TestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id=uuid.uuid4(),
            person_id=uuid.uuid4(),
            legacy_employee_id=55,
        )

    def test_empty_school_gets_honest_default_navigation_catalog(self):
        self.assertEqual(SelfServiceCatalogItem.objects.filter(tenant_id=77).count(), 0)

        result = SelfCatalogService(self.context).search(limit=100)

        self.assertEqual(result["total"], len(DEFAULT_SELF_SERVICES))
        self.assertEqual(
            set(SelfServiceCatalogItem.objects.filter(tenant_id=77).values_list("source_domain", flat=True)),
            {"HR03", "HR04", "HR05", "HR06", "HR07", "HR12", "HR13", "HR14", "HR15", "HR16"},
        )
        self.assertTrue(all(item["route"].startswith("/hr/self/") for item in result["items"]))
        self.assertTrue(all(item["name"].startswith("查看") for item in result["items"]))

    def test_existing_school_catalog_is_not_overwritten_or_mixed_with_defaults(self):
        SelfServiceCatalogItem.objects.create(
            tenant_id=77,
            service_code="SCHOOL_CUSTOM",
            name="学校自定义服务",
            source_domain="HR03",
            action_key="VIEW_CUSTOM",
            route="/hr/self/files/",
            audience="SELF",
            enabled=False,
            sort_order=1,
        )

        created = ensure_default_catalog_if_empty(77)

        self.assertEqual(created, 0)
        self.assertEqual(SelfServiceCatalogItem.objects.filter(tenant_id=77).count(), 1)
        self.assertFalse(SelfServiceCatalogItem.objects.get(tenant_id=77).enabled)
