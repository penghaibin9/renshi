"""Position names must follow formal, school-scoped effective organization facts."""

from datetime import timedelta

from django.test import TestCase, override_settings

from hr_structure.models import HrOrganizationVersion
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.position import PositionSelector
from hr_structure.tests.test_initial_setup import Fixture, SETTINGS


@override_settings(**SETTINGS)
class PositionNameTests(Fixture, TestCase):
    def test_new_position_displays_department_name_and_preserves_stable_code(self):
        receipt, _ = self.command()
        selector = PositionSelector(Hr02Scope("SCHOOL", self.school.pk), self.today)
        with self.assertNumQueries(4):
            result = selector.list_positions(page=1, page_size=20)
        row = result["items"][0]
        self.assertEqual(row["organizationName"], "教务处")
        self.assertEqual(row["organizationCode"], "OFFICE")
        self.assertEqual(row["occupancyStatus"], "VACANT")
        detail = selector.get_position(receipt.position_id)
        self.assertEqual(detail["organizationName"], "教务处")

    def test_future_and_draft_names_do_not_overwrite_current_display(self):
        receipt, _ = self.command()
        version = receipt.department_version
        future = self.today + timedelta(days=10)
        version.validity_to = future
        version.save(update_fields=["validity_to"])
        HrOrganizationVersion.objects.create(
            organization_id_id=version.organization_id_id, tenant_id=self.school.pk,
            name="教学运行中心", org_type="OFFICE", validity_from=future,
            version_no=2, status="EFFECTIVE",
        )
        HrOrganizationVersion.objects.create(
            organization_id_id=version.organization_id_id, tenant_id=self.school.pk,
            name="尚未批准的名称", org_type="OFFICE", validity_from=self.today,
            version_no=3, status="DRAFT",
        )
        scope = Hr02Scope("SCHOOL", self.school.pk)
        self.assertEqual(PositionSelector(scope, self.today).get_position(receipt.position_id)["organizationName"], "教务处")
        self.assertEqual(PositionSelector(scope, future).get_position(receipt.position_id)["organizationName"], "教学运行中心")

    def test_foreign_version_reference_cannot_supply_display_name(self):
        receipt, _ = self.command()
        # Intentionally corrupt tenant metadata to exercise the query boundary.
        HrOrganizationVersion.objects.create(
            organization_id_id=receipt.department_version.organization_id_id,
            tenant_id=self.other.pk, name="其他学校不可泄漏名称", org_type="OFFICE",
            validity_from=self.today, version_no=9, status="EFFECTIVE",
        )
        row = PositionSelector(Hr02Scope("SCHOOL", self.school.pk), self.today).get_position(receipt.position_id)
        self.assertEqual(row["organizationName"], "教务处")
