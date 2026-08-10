from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_structure.scope import Hr02Scope
from hr_structure.services.position import PositionService, PositionServiceError


class PositionReservationCapacityGateTests(TestCase):
    def setUp(self):
        self.service = PositionService(Hr02Scope("SCHOOL", tenant_id=77))

    @patch("hr_staff.services.effective_dated_query_service.EffectiveDatedQueryService")
    @patch("hr_structure.services.position.HrPositionReservation.objects")
    @patch("hr_structure.services.position.HrPosition.objects")
    def test_existing_hr03_occupancy_blocks_new_reservation(
        self,
        position_objects,
        reservation_objects,
        query_service_cls,
    ):
        reservation_objects.filter.return_value.first.return_value = None
        self.service.expire_overdue = MagicMock(return_value=0)

        position = MagicMock()
        position.id = 5
        position.max_incumbents = 1
        position_objects.select_for_update.return_value.filter.return_value.first.return_value = position
        query_service_cls.return_value.position_occupancy_as_of.return_value = 1

        held_qs = MagicMock()
        held_qs.aggregate.return_value = {"total": 0}
        # first filter is idempotency lookup; second is HELD capacity lookup
        reservation_objects.filter.side_effect = [
            MagicMock(first=MagicMock(return_value=None)),
            held_qs,
        ]

        with self.assertRaises(PositionServiceError) as cm:
            self.service.reserve(
                source_domain="HR14",
                source_business_type="APPOINTMENT",
                source_business_id="CASE-1",
                position_id=5,
                idempotency_key="hr14:case-1",
            )

        self.assertEqual(cm.exception.code, "HR02_POSITION_NOT_AVAILABLE")
        query_service_cls.assert_called_once_with(77)
        reservation_objects.create.assert_not_called()

    @patch("hr_structure.services.position.HrPositionReservation.objects")
    @patch("hr_structure.services.position.HrPositionPool.objects")
    def test_pool_only_reservation_does_not_depend_on_position_branch_local_time_import(
        self,
        pool_objects,
        reservation_objects,
    ):
        self.service.expire_overdue = MagicMock(return_value=0)
        idempotency_qs = MagicMock()
        idempotency_qs.first.return_value = None
        held_qs = MagicMock()
        held_qs.aggregate.return_value = {"total": 0}
        reservation_objects.filter.side_effect = [idempotency_qs, held_qs]

        pool = MagicMock()
        pool.authorized_count = 2
        pool_objects.select_for_update.return_value.filter.return_value.first.return_value = pool
        created = MagicMock()
        reservation_objects.create.return_value = created

        result = self.service.reserve(
            source_domain="HR14",
            source_business_type="BATCH",
            source_business_id="BATCH-1",
            position_pool_id=9,
            idempotency_key="hr14:batch-1",
        )

        self.assertIs(result, created)
        reservation_objects.create.assert_called_once()
