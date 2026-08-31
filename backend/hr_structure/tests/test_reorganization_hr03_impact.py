from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from hr_structure.scope import Hr02Scope
from hr_structure.services.reorganization import ReorganizationService


class ReorganizationHr03ImpactTests(SimpleTestCase):
    def test_active_hr03_assignments_require_mapping(self):
        item = SimpleNamespace(entity_type="org", entity_id="17")
        case = SimpleNamespace(
            items=SimpleNamespace(all=Mock(return_value=[item])),
            requested_effective_date=date(2026, 9, 1),
        )
        assignment_window = Mock()
        assignment_window.filter.return_value.count.return_value = 2

        with (
            patch("hr_structure.models.HrOrganizationVersion.objects.filter") as org_versions,
            patch("hr_structure.models.HrPosition.objects.filter") as positions,
            patch("hr_structure.models.HrPositionReservation.objects.filter") as reservations,
            patch("hr_staff.models.HrStaffAssignment.objects.filter", return_value=assignment_window) as assignments,
        ):
            org_versions.return_value.count.return_value = 0
            positions.return_value.count.return_value = 0
            reservations.return_value.count.return_value = 0

            result = ReorganizationService(Hr02Scope(scope_type="SCHOOL", tenant_id=9)).impact_analysis(case)

        assignments.assert_called_once_with(
            tenant_id=9,
            organization_id=17,
            status="ACTIVE",
            effective_from__lte=date(2026, 9, 1),
        )
        self.assertEqual(result["summary"]["requiresMapping"], 1)
        self.assertIn(
            "ORG_HAS_STAFF_ASSIGNMENTS",
            {check["code"] for check in result["checks"]},
        )
        self.assertNotIn(
            "HR03_ASSIGNMENT_PENDING",
            {check["code"] for check in result["checks"]},
        )
