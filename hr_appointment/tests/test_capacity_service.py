import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import AppointmentQuotaReservation
from hr_appointment.services.capacity_service import (
    AppointmentCapacityError,
    AppointmentCapacityService,
)
from hr_structure.services.position import PositionServiceError


class AppointmentCapacityServiceTests(TestCase):
    def _case(self):
        return SimpleNamespace(
            id=uuid.uuid4(),
            position_instance_id=31,
        )

    @patch("hr_structure.services.position.PositionService")
    @patch("hr_appointment.services.capacity_service.AppointmentQuotaService")
    def test_prepare_owns_hr02_hold_by_exact_application(
        self, quota_service_cls, position_service_cls
    ):
        service = AppointmentCapacityService(77, actor_user_id=9)
        case = self._case()
        service._lock_case = MagicMock(return_value=case)
        quota = SimpleNamespace(
            id=uuid.uuid4(),
            status=AppointmentQuotaReservation.Status.ACTIVE,
        )
        quota_service_cls.return_value.reserve.return_value = quota
        expires_at = timezone.now() + timedelta(days=7)
        position_reservation = SimpleNamespace(
            id=41,
            position_id_id=31,
            source_domain="HR14",
            source_business_type="APPOINTMENT_CASE",
            source_business_id=str(case.id),
        )
        position_service_cls.return_value.reserve.return_value = position_reservation

        result = service.prepare(
            case_id=case.id,
            quota_pool_id=uuid.uuid4(),
            expires_at=expires_at,
        )

        self.assertIs(result.quota_reservation, quota)
        self.assertIs(result.position_reservation, position_reservation)
        quota_service_cls.assert_called_once_with(77, actor_user_id=9)
        quota_kwargs = quota_service_cls.return_value.reserve.call_args.kwargs
        self.assertEqual(quota_kwargs["application_case_id"], case.id)
        self.assertEqual(quota_kwargs["units"], 1)
        position_kwargs = position_service_cls.return_value.reserve.call_args.kwargs
        self.assertEqual(position_kwargs["source_domain"], "HR14")
        self.assertEqual(position_kwargs["source_business_type"], "APPOINTMENT_CASE")
        self.assertEqual(position_kwargs["source_business_id"], str(case.id))
        self.assertEqual(position_kwargs["position_id"], 31)
        self.assertEqual(position_kwargs["count"], 1)
        self.assertEqual(position_kwargs["fte"], Decimal("1.00"))
        self.assertEqual(position_kwargs["expires_at"], expires_at)
        self.assertIn(str(case.id), position_kwargs["idempotency_key"])

    @patch("hr_structure.services.position.PositionService")
    @patch("hr_appointment.services.capacity_service.AppointmentQuotaService")
    def test_hr02_capacity_failure_is_fail_closed(
        self, quota_service_cls, position_service_cls
    ):
        service = AppointmentCapacityService(77, actor_user_id=9)
        case = self._case()
        service._lock_case = MagicMock(return_value=case)
        quota_service_cls.return_value.reserve.return_value = SimpleNamespace(id=uuid.uuid4())
        position_service_cls.return_value.reserve.side_effect = PositionServiceError(
            "HR02_POSITION_CAPACITY_EXCEEDED",
            "岗位容量不足",
        )

        with self.assertRaises(AppointmentCapacityError) as ctx:
            service.prepare(
                case_id=case.id,
                quota_pool_id=uuid.uuid4(),
            )

        self.assertEqual(ctx.exception.code, "HR02_POSITION_CAPACITY_EXCEEDED")

    @patch("hr_structure.services.position.PositionService")
    @patch("hr_appointment.services.capacity_service.AppointmentQuotaService")
    def test_idempotency_receipt_must_still_match_case_owner(
        self, quota_service_cls, position_service_cls
    ):
        service = AppointmentCapacityService(77, actor_user_id=9)
        case = self._case()
        service._lock_case = MagicMock(return_value=case)
        quota_service_cls.return_value.reserve.return_value = SimpleNamespace(id=uuid.uuid4())
        position_service_cls.return_value.reserve.return_value = SimpleNamespace(
            id=41,
            position_id_id=31,
            source_domain="HR14",
            source_business_type="APPOINTMENT_CASE",
            source_business_id=str(uuid.uuid4()),
        )

        with self.assertRaises(AppointmentCapacityError) as ctx:
            service.prepare(
                case_id=case.id,
                quota_pool_id=uuid.uuid4(),
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_CAPACITY_RECEIPT_CONFLICT")
