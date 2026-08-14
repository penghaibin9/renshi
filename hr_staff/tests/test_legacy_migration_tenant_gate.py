from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_staff.legacy.migration import MigrationService, MigrationTenantScopeError


class LegacyMigrationTenantGateTests(TestCase):
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


class LegacyMigrationWave2AtomicityTests(TestCase):
    @patch("hr_staff.legacy.migration.transaction.atomic")
    @patch("hr_staff.services.assignment_service.AssignmentService")
    @patch("hr_staff.services.employment_service.EmploymentService")
    def test_assignment_failure_is_caught_only_after_nested_savepoint_boundary(
        self,
        employment_service_cls,
        assignment_service_cls,
        inner_atomic,
    ):
        staff = SimpleNamespace(id=20, tenant_id=1, legacy_employee_id=10)
        relationship = SimpleNamespace(id="rel-1")
        employment_service_cls.return_value.start_relationship.return_value = relationship
        assignment_service_cls.return_value.create_assignment.side_effect = RuntimeError(
            "assignment failed"
        )
        inner_atomic.return_value = MagicMock()

        result = MigrationService(tenant_id=1).wave2_employment(
            staff=staff,
            legacy_work_info={"date_joining": None},
            legacy_department_id=7,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("assignment failed", result["reason"])
        inner_atomic.assert_called_once_with()
        employment_service_cls.return_value.start_relationship.assert_called_once()
        assignment_service_cls.return_value.create_assignment.assert_called_once()