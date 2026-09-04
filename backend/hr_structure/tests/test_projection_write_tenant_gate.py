from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_structure.projections.horilla import (
    HorillaStructureProjectionService,
    LegacyProjectionError,
)


def _version(*, tenant_id=77, org_tenant_id=77):
    org = SimpleNamespace(tenant_id=org_tenant_id, org_dimension="ADMIN")
    return SimpleNamespace(
        tenant_id=tenant_id,
        organization_id=org,
        organization_id_id=1001,
        name="教务处",
    )


class ProjectionWriteTenantGateTests(SimpleTestCase):
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_cross_tenant_authority_object_is_rejected_before_legacy_lookup(self, link_objects):
        with self.assertRaises(LegacyProjectionError):
            HorillaStructureProjectionService(77).project_organization(
                _version(tenant_id=88, org_tenant_id=88)
            )
        link_objects.filter.assert_not_called()

    @patch("hr_structure.projections.horilla._legacy_department_model")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_existing_legacy_link_can_only_resolve_inside_tenant(self, link_objects, department_model):
        department_objects = department_model.return_value.objects
        link = SimpleNamespace(legacy_pk="9", projection_hash="old")
        link_objects.filter.return_value.first.return_value = link
        department_objects.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(LegacyProjectionError, "HR02_LEGACY_LINK_TENANT_MISMATCH"):
            HorillaStructureProjectionService(77).project_organization(_version())

        department_objects.filter.assert_called_once_with(id=9, company_id=77)

    @patch("hr_structure.projections.horilla._legacy_department_model")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_new_legacy_department_is_bound_to_current_tenant(self, link_objects, department_model):
        department_objects = department_model.return_value.objects
        link_objects.filter.return_value.first.return_value = None
        department = MagicMock()
        department.id = 9
        department_objects.create.return_value = department
        created_link = MagicMock()
        link_objects.create.return_value = created_link

        result = HorillaStructureProjectionService(77).project_organization(_version())

        department_objects.create.assert_called_once_with(department="教务处")
        department.company_id.add.assert_called_once_with(77)
        department.save.assert_called_once_with(update_fields=["department"])
        self.assertIs(result, created_link)

    def test_root_company_must_match_service_tenant(self):
        with self.assertRaisesRegex(LegacyProjectionError, "HR02_CROSS_TENANT_COMPANY"):
            HorillaStructureProjectionService(77).create_root_from_company(
                SimpleNamespace(id=88, company="另一学校")
            )
