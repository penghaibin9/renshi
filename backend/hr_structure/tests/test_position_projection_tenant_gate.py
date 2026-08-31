from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_structure.projections.horilla import (
    HorillaStructureProjectionService,
    LegacyProjectionError,
)


def _position(*, tenant_id=77, org_tenant_id=77, catalog_tenant_id=77):
    return SimpleNamespace(
        id=501,
        tenant_id=tenant_id,
        position_code="POS-001",
        organization_id_id=1001,
        organization_id=SimpleNamespace(tenant_id=org_tenant_id),
        post_catalog_version_id=SimpleNamespace(
            tenant_id=catalog_tenant_id,
            name="专任教师",
        ),
        lifecycle_status="ACTIVE",
    )


def _first(value):
    queryset = MagicMock()
    queryset.first.return_value = value
    return queryset


class PositionProjectionTenantGateTests(SimpleTestCase):
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_cross_tenant_position_is_rejected_before_legacy_lookup(self, link_objects):
        with self.assertRaisesRegex(LegacyProjectionError, "HR02_CROSS_TENANT_POSITION"):
            HorillaStructureProjectionService(77).project_position(
                _position(tenant_id=88, org_tenant_id=88, catalog_tenant_id=88)
            )
        link_objects.filter.assert_not_called()

    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_position_requires_mapped_organization_before_projection(self, link_objects):
        link_objects.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(
            LegacyProjectionError, "HR02_POSITION_ORG_LEGACY_LINK_REQUIRED"
        ):
            HorillaStructureProjectionService(77).project_position(_position())

    @patch("base.models.Department.objects")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_mapped_department_must_still_belong_to_current_tenant(
        self, link_objects, department_objects
    ):
        link_objects.filter.return_value.first.return_value = SimpleNamespace(legacy_pk="9")
        department_objects.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(
            LegacyProjectionError, "HR02_POSITION_ORG_LEGACY_TENANT_MISMATCH"
        ):
            HorillaStructureProjectionService(77).project_position(_position())

        department_objects.filter.assert_called_once_with(id=9, company_id=77)

    @patch("base.models.JobPosition.objects")
    @patch("base.models.Department.objects")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_new_job_position_is_bound_to_current_tenant(
        self, link_objects, department_objects, job_position_objects
    ):
        org_link = SimpleNamespace(legacy_pk="9")
        link_objects.filter.side_effect = [_first(org_link), _first(None)]
        department = MagicMock()
        department_objects.filter.return_value.first.return_value = department
        legacy_position = MagicMock()
        legacy_position.id = 55
        job_position_objects.create.return_value = legacy_position
        created_link = MagicMock()
        link_objects.create.return_value = created_link

        result = HorillaStructureProjectionService(77).project_position(_position())

        job_position_objects.create.assert_called_once_with(
            job_position="专任教师",
            department_id=department,
        )
        legacy_position.company_id.add.assert_called_once_with(77)
        self.assertIs(result, created_link)

    @patch("base.models.JobPosition.objects")
    @patch("base.models.Department.objects")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_existing_job_position_link_can_only_resolve_inside_tenant(
        self, link_objects, department_objects, job_position_objects
    ):
        org_link = SimpleNamespace(legacy_pk="9")
        position_link = SimpleNamespace(legacy_pk="55", projection_hash="old")
        link_objects.filter.side_effect = [_first(org_link), _first(position_link)]
        department_objects.filter.return_value.first.return_value = MagicMock()
        job_position_objects.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(
            LegacyProjectionError, "HR02_POSITION_LEGACY_TENANT_MISMATCH"
        ):
            HorillaStructureProjectionService(77).project_position(_position())

        job_position_objects.filter.assert_called_once_with(id=55, company_id=77)

    @patch("base.models.JobPosition.objects")
    @patch("base.models.Department.objects")
    @patch("hr_structure.projections.horilla.HrLegacyObjectLink.objects")
    def test_unchanged_projection_hash_skips_legacy_job_position_write(
        self, link_objects, department_objects, job_position_objects
    ):
        position = _position()
        service = HorillaStructureProjectionService(77)
        expected_hash = service._hash(
            {
                "positionCode": position.position_code,
                "name": position.post_catalog_version_id.name,
                "organizationId": str(position.organization_id_id),
                "lifecycleStatus": position.lifecycle_status,
            }
        )
        org_link = SimpleNamespace(legacy_pk="9")
        position_link = SimpleNamespace(legacy_pk="55", projection_hash=expected_hash)
        link_objects.filter.side_effect = [_first(org_link), _first(position_link)]
        department_objects.filter.return_value.first.return_value = MagicMock()

        result = service.project_position(position)

        self.assertIs(result, position_link)
        job_position_objects.filter.assert_not_called()
        job_position_objects.create.assert_not_called()
