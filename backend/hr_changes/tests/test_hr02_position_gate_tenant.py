from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_changes.integrations.hr02 import Hr02GateError, PositionGate


class PositionGateTenantTests(SimpleTestCase):
    def _case(self, *, tenant_id=77, action="POSITION_TRANSFER", position_tenant=77):
        return SimpleNamespace(
            id=9,
            tenant_id=tenant_id,
            action_id=SimpleNamespace(code=action),
            target_position_id=SimpleNamespace(
                id=5,
                tenant_id=position_tenant,
                max_incumbents=2,
            ),
        )

    def test_cross_tenant_case_is_rejected(self):
        with self.assertRaisesRegex(Hr02GateError, "change case tenant mismatch"):
            PositionGate(77).target_position(self._case(tenant_id=88))

    def test_cross_tenant_position_is_rejected(self):
        with self.assertRaisesRegex(Hr02GateError, "target position tenant mismatch"):
            PositionGate(77).target_position(self._case(position_tenant=88))

    @patch("hr_changes.integrations.hr02.HrPositionReservation.objects")
    def test_required_commit_fails_when_reservation_missing(self, reservation_objects):
        reservation_objects.filter.return_value.order_by.return_value.first.return_value = None

        with self.assertRaisesRegex(Hr02GateError, "目标岗位预占缺失"):
            PositionGate(77).require_commit_for_case(self._case())

    @patch("hr_changes.integrations.hr02.HrPositionReservation.objects")
    @patch("hr_changes.integrations.hr02.PositionService")
    def test_capacity_counts_only_current_tenant_held_reservations(
        self,
        position_service_cls,
        reservation_objects,
    ):
        reservation_objects.filter.return_value.count.return_value = 1
        with patch(
            "hr_staff.services.effective_dated_query_service.EffectiveDatedQueryService.position_occupancy_as_of",
            return_value=0,
        ):
            blockers = PositionGate(77).check_capacity(self._case())

        reservation_objects.filter.assert_called_once_with(
            tenant_id=77,
            position_id=self._case().target_position_id,
            status="HELD",
        )
        self.assertEqual(blockers, [])

    def test_idempotency_key_contains_tenant(self):
        self.assertEqual(PositionGate(77)._idempotency_key(9), "HR06-TENANT-77-CASE-9")
