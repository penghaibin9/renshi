from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_self.services.catalog_service import SelfCatalogError, SelfCatalogService
from hr_self.services.identity_service import SelfIdentityContext


class SelfCatalogServiceTests(TestCase):
    def setUp(self):
        self.context = SelfIdentityContext(
            tenant_id=77,
            user_id=9,
            staff_id="00000000-0000-0000-0000-000000000101",
            person_id="00000000-0000-0000-0000-000000000201",
            legacy_employee_id=55,
        )
        self.service = SelfCatalogService(self.context)

    @patch("hr_self.services.catalog_service.SelfServicePinnedService.objects")
    @patch("hr_self.services.catalog_service.SelfServiceCatalogItem.objects")
    def test_pin_uses_resolved_self_staff_not_client_identity(
        self, catalog_objects, pin_objects
    ):
        catalog_qs = MagicMock()
        catalog_qs.first.return_value = SimpleNamespace(service_code="MY_PROFILE")
        catalog_objects.filter.return_value.order_by.return_value = catalog_qs
        pin = MagicMock()
        pin_objects.update_or_create.return_value = (pin, True)

        result = self.service.pin(service_code="MY_PROFILE", sort_order=5)

        self.assertIs(result, pin)
        catalog_objects.filter.assert_called_once_with(
            tenant_id=77,
            service_code="MY_PROFILE",
            enabled=True,
        )
        pin_objects.update_or_create.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
            service_code="MY_PROFILE",
            defaults={"sort_order": 5},
        )

    @patch("hr_self.services.catalog_service.SelfServiceCatalogItem.objects")
    def test_missing_or_cross_tenant_catalog_item_fails_closed(self, catalog_objects):
        catalog_qs = MagicMock()
        catalog_qs.first.return_value = None
        catalog_objects.filter.return_value.order_by.return_value = catalog_qs

        with self.assertRaises(SelfCatalogError) as cm:
            self.service.pin(service_code="OTHER_TENANT_SERVICE")

        self.assertEqual(cm.exception.code, "SELF_SERVICE_NOT_AVAILABLE")

    @patch("hr_self.services.catalog_service.SelfServicePinnedService.objects")
    def test_unpin_is_always_scoped_to_resolved_self_identity(self, pin_objects):
        queryset = MagicMock()
        queryset.delete.return_value = (1, {"hr_self.SelfServicePinnedService": 1})
        pin_objects.filter.return_value = queryset

        deleted = self.service.unpin(service_code="MY_PROFILE")

        self.assertEqual(deleted, 1)
        pin_objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
            service_code="MY_PROFILE",
        )

    @patch("hr_self.services.catalog_service.SelfServicePinnedService.objects")
    def test_list_pins_never_reads_other_staff(self, pin_objects):
        queryset = MagicMock()
        ordered = MagicMock()
        queryset.order_by.return_value = ordered
        pin_objects.filter.return_value = queryset

        result = self.service.list_pins()

        self.assertIs(result, ordered)
        pin_objects.filter.assert_called_once_with(
            tenant_id=77,
            staff_id=self.context.staff_id,
        )
        queryset.order_by.assert_called_once_with("sort_order", "service_code")
