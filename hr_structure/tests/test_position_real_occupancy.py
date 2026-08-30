"""HR02 岗位占用必须来自 HR03 有效任职，预占不得冒充在岗人员。"""

import json
from datetime import date, timedelta
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.utils import timezone

from hr_staff.models import HrStaffAssignment
from hr_staff.services.employment_service import EmploymentService
from hr_staff.tests.factories import make_org, make_person, make_staff
from hr_structure.api.views import position_control_summary
from hr_structure.models import HrPositionReservation
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.position import PositionSelector
from hr_structure.services.position import PositionService
from hr_structure.services.post_catalog import PostCatalogService


class PositionRealOccupancyTests(TestCase):
    tenant_id = 701
    other_tenant_id = 702

    def setUp(self):
        self.as_of = timezone.localdate()
        self.scope = Hr02Scope("SCHOOL", tenant_id=self.tenant_id)
        self.org = make_org(
            self.tenant_id, "REAL-OCC-ORG", "真实占用学院", date(2020, 1, 1)
        )
        catalog = PostCatalogService(self.scope).create_catalog(
            stable_code="REAL-OCC-CAT",
            name="真实占用岗位目录",
            category="PROFESSIONAL_TECHNICAL",
            validity_from=date(2020, 1, 1),
        )
        self.position = PositionService(self.scope).create_position(
            position_code="REAL-OCC-P1",
            organization_id=self.org.id,
            post_catalog_version_id=catalog.versions.get().id,
            max_incumbents=4,
            validity_from=date(2020, 1, 1),
        )

    def _relationship(self, tenant_id, suffix, *, effective_from=date(2020, 1, 1)):
        person = make_person(tenant_id, f"任职人员-{suffix}")
        staff = make_staff(tenant_id, person, f"OCC-{tenant_id}-{suffix}")
        return EmploymentService(tenant_id).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=effective_from,
        )

    def _assignment(
        self,
        tenant_id,
        suffix,
        *,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        status="ACTIVE",
    ):
        relationship = self._relationship(
            tenant_id, suffix, effective_from=effective_from
        )
        return HrStaffAssignment.objects.create(
            tenant_id=tenant_id,
            employment_relationship_id=relationship,
            organization_id=self.org,
            position_id=self.position,
            assignment_type="PRIMARY",
            effective_from=effective_from,
            effective_to=effective_to,
            status=status,
        )

    def _held(self, *, tenant_id=None, count=1, suffix="1", expires_at=None):
        return HrPositionReservation.objects.create(
            tenant_id=tenant_id or self.tenant_id,
            reservation_no=f"REAL-OCC-R-{suffix}",
            position_id=self.position,
            source_domain="hr04",
            source_business_type="requisition",
            source_business_id=f"REAL-OCC-BIZ-{suffix}",
            reserved_count=count,
            status=HrPositionReservation.Status.HELD,
            expires_at=expires_at or timezone.now() + timedelta(days=2),
            idempotency_key=f"REAL-OCC-IDEM-{tenant_id or self.tenant_id}-{suffix}",
        )

    def test_assignment_and_reservation_are_separate_and_reduce_availability(self):
        self._assignment(self.tenant_id, "active")
        self._held(count=2)
        self._held(tenant_id=self.other_tenant_id, count=3, suffix="foreign-now")
        self._held(
            count=4,
            suffix="expired",
            expires_at=timezone.now() - timedelta(days=1),
        )

        selector = PositionSelector(self.scope, as_of=self.as_of)
        dto = selector.get_position(self.position.id)
        availability = selector.availability(position_id=self.position.id)

        self.assertEqual(dto["occupiedCount"], 1)
        self.assertEqual(dto["reservedCount"], 2)
        self.assertEqual(dto["availableCount"], 1)
        self.assertEqual(dto["occupancyStatus"], "PARTIALLY_FILLED")
        self.assertEqual(dto["dataBasis"], "AUTHORITATIVE_EFFECTIVE_FACT")
        self.assertEqual(availability["occupied"], 1)
        self.assertEqual(availability["reserved"], 2)
        self.assertEqual(availability["free"], 1)
        self.assertTrue(availability["available"])

    def test_as_of_and_tenant_scope_are_applied_to_assignments_and_reservations(self):
        self._assignment(
            self.tenant_id,
            "historical",
            effective_from=date(2023, 1, 1),
            effective_to=date(2025, 1, 1),
            status="ENDED",
        )
        self._assignment(
            self.tenant_id,
            "future",
            effective_from=date(2025, 1, 1),
        )
        # 故意制造跨 tenant 父链脏数据，查询必须仍以 assignment/reservation tenant 为门。
        self._assignment(self.other_tenant_id, "foreign")
        self._held(tenant_id=self.other_tenant_id, count=3, suffix="foreign")

        historical = PositionSelector(
            self.scope, as_of=date(2024, 6, 1)
        ).get_position(self.position.id)
        current = PositionSelector(
            self.scope, as_of=date(2025, 6, 1)
        ).get_position(self.position.id)

        self.assertEqual(historical["occupiedCount"], 1)
        self.assertEqual(current["occupiedCount"], 1)
        self.assertEqual(current["reservedCount"], 0)

    def test_position_list_batches_occupancy_and_reservations(self):
        catalog_version = self.position.post_catalog_version_id
        PositionService(self.scope).create_position(
            position_code="REAL-OCC-P2",
            organization_id=self.org.id,
            post_catalog_version_id=catalog_version.id,
            max_incumbents=2,
            validity_from=date(2020, 1, 1),
        )
        PositionService(self.scope).create_position(
            position_code="REAL-OCC-P3",
            organization_id=self.org.id,
            post_catalog_version_id=catalog_version.id,
            max_incumbents=1,
            validity_from=date(2020, 1, 1),
        )
        self._assignment(self.tenant_id, "batch")

        with self.assertNumQueries(4):
            result = PositionSelector(self.scope, as_of=self.as_of).list_positions(
                page=1, page_size=20
            )

        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["items"]), 3)

    def test_summary_uses_hr03_occupied_and_exposes_reserved_and_available(self):
        self._assignment(self.tenant_id, "summary")
        self._held(count=2, suffix="summary")
        request = RequestFactory().get(
            "/api/hr/v1/structure/position-control/summary",
            {"asOf": self.as_of.isoformat()},
        )

        with patch("hr_structure.api.views._make_scope", return_value=self.scope):
            response = position_control_summary(request)

        payload = json.loads(response.content)
        self.assertEqual(payload["authorized"], 4)
        self.assertEqual(payload["occupied"], 1)
        self.assertEqual(payload["reserved"], 2)
        self.assertEqual(payload["available"], 1)
        self.assertEqual(payload["vacant"], 3)
        self.assertEqual(payload["over"], 0)
        self.assertEqual(payload["dataBasis"], "AUTHORITATIVE_EFFECTIVE_FACT")

    def test_summary_does_not_offset_an_overfilled_position_with_an_empty_one(self):
        catalog_version = self.position.post_catalog_version_id
        empty = PositionService(self.scope).create_position(
            position_code="REAL-OCC-EMPTY",
            organization_id=self.org.id,
            post_catalog_version_id=catalog_version.id,
            max_incumbents=1,
            validity_from=date(2020, 1, 1),
        )
        self.position.max_incumbents = 1
        self.position.save(update_fields=["max_incumbents"])
        self._assignment(self.tenant_id, "over-1")
        self._assignment(self.tenant_id, "over-2")

        summary = PositionSelector(self.scope, as_of=self.as_of).control_summary()
        dto = PositionSelector(self.scope, as_of=self.as_of).get_position(
            self.position.id
        )

        self.assertEqual(summary["authorized"], 2)
        self.assertEqual(summary["occupied"], 2)
        self.assertEqual(summary["over"], 1)
        self.assertEqual(summary["vacant"], 1)
        self.assertEqual(summary["available"], 1)
        self.assertEqual(dto["occupancyStatus"], "OVERFILLED")
        self.assertEqual(empty.max_incumbents, 1)
