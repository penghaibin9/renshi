from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_structure.projections.horilla import HorillaStructureProjectionService


class HorillaStructureProjectionTenantScopeTests(SimpleTestCase):
    @patch("employee.models.EmployeeWorkInformation.objects")
    @patch("base.models.Department.objects")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_reconcile_report_scopes_every_legacy_query_to_tenant(
        self,
        legacy_link_objects,
        department_objects,
        work_info_objects,
    ):
        department_qs = MagicMock()
        department_qs.count.return_value = 2
        department_objects.filter.return_value = department_qs

        mapped_qs = MagicMock()
        mapped_qs.count.return_value = 1
        legacy_link_objects.filter.return_value = mapped_qs

        work_info_qs = MagicMock()
        unmapped_qs = MagicMock()
        unmapped_qs.count.return_value = 0
        work_info_qs.filter.return_value = unmapped_qs
        work_info_objects.filter.return_value = work_info_qs

        report = HorillaStructureProjectionService(tenant_id=77).reconcile_report()

        department_objects.filter.assert_called_once_with(
            company_id=77,
            is_active=True,
        )
        legacy_link_objects.filter.assert_called_once_with(
            tenant_id=77,
            legacy_model="department",
            link_status="MAPPED",
        )
        work_info_objects.filter.assert_called_once_with(
            company_id_id=77,
            employee_id__is_active=True,
        )
        work_info_qs.filter.assert_called_once_with(department_id__isnull=True)
        self.assertEqual(report["tenantId"], 77)
