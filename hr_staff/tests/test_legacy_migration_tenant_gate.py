from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_staff.legacy.migration import MigrationService, MigrationTenantScopeError


class LegacyMigrationTenantGateTests(SimpleTestCase):
    def test_wave1_rejects_cross_tenant_employee_before_authority_write(self):
        employee = SimpleNamespace(
            id=10,
            employee_work_info=SimpleNamespace(company_id_id=2),
        )

        with self.assertRaises(MigrationTenantScopeError):
            MigrationService(tenant_id=1).wave1_person_staff(employee=employee)

    def test_wave1_rejects_employee_without_tenant_work_info(self):
        employee = SimpleNamespace(id=10, employee_work_info=None)

        with self.assertRaises(MigrationTenantScopeError):
            MigrationService(tenant_id=1).wave1_person_staff(employee=employee)

    def test_wave2_rejects_cross_tenant_staff_before_relationship_write(self):
        staff = SimpleNamespace(id=20, tenant_id=2)

        with self.assertRaises(MigrationTenantScopeError):
            MigrationService(tenant_id=1).wave2_employment(staff=staff)

    def test_migration_service_requires_tenant(self):
        with self.assertRaises(MigrationTenantScopeError):
            MigrationService(tenant_id=0)
