from django.test import SimpleTestCase

from hr_self.models import SelfServiceCatalogItem, SelfServicePinnedService


class Hr17ModelContractTests(SimpleTestCase):
    def test_catalog_points_to_source_domain_instead_of_copying_business_fact(self):
        fields = {field.name for field in SelfServiceCatalogItem._meta.fields}
        assert "source_domain" in fields
        assert "action_key" in fields
        assert "business_status" not in fields

    def test_pins_are_scoped_by_tenant_staff_and_service(self):
        names = {constraint.name for constraint in SelfServicePinnedService._meta.constraints}
        assert "uq_hr17_pin_tenant_staff_service" in names

    def test_tenant_is_fail_closed_before_database_write(self):
        item = SelfServiceCatalogItem(
            tenant_id=None,
            service_code="PAYSLIP",
            name="Payslip",
            source_domain="HR15",
            action_key="view_payslip",
            route="/self/payroll/payslip",
        )
        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            item.save()
