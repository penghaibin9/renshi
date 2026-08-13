import uuid

from django.test import TestCase

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentQuotaPool,
    AppointmentQuotaReservation,
)
from hr_appointment.services.quota_service import (
    AppointmentQuotaError,
    AppointmentQuotaService,
)


class AppointmentQuotaServiceTests(TestCase):
    def setUp(self):
        self.tenant = 101
        self.batch = AppointmentBatch.objects.create(
            tenant_id=self.tenant,
            batch_no="B-2026-01",
            name="2026 专技岗位竞聘",
            policy_version_id=uuid.uuid4(),
            status=AppointmentBatch.Status.APPLICATION_CLOSED,
        )
        self.pool = AppointmentQuotaPool.objects.create(
            tenant_id=self.tenant,
            batch=self.batch,
            scope_type="SCHOOL",
            category_code="PROFESSIONAL_TECHNICAL",
            exact_level_code="PT-7",
            authorized=2,
            occupied=0,
            reserved=0,
        )
        self.case = AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant,
            case_no="A-2026-001",
            person_id=uuid.uuid4(),
            policy_version_id=self.batch.policy_version_id,
            position_instance_id=1001,
            batch_no=self.batch.batch_no,
            requested_level_code="PT-7",
            status=AppointmentApplicationCase.Status.ELIGIBLE,
        )
        self.service = AppointmentQuotaService(self.tenant, actor_user_id=9)

    def test_reserve_is_idempotent_and_does_not_double_count(self):
        first = self.service.reserve(
            application_case_id=self.case.id, quota_pool_id=self.pool.id
        )
        second = self.service.reserve(
            application_case_id=self.case.id, quota_pool_id=self.pool.id
        )
        self.assertEqual(first.id, second.id)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 1)
        self.assertEqual(self.pool.available, 1)

    def test_exhausted_quota_blocks_second_application(self):
        self.pool.authorized = 1
        self.pool.save(update_fields=["authorized", "updated_at"])
        self.service.reserve(application_case_id=self.case.id, quota_pool_id=self.pool.id)

        other_case = AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant,
            case_no="A-2026-002",
            person_id=uuid.uuid4(),
            policy_version_id=self.batch.policy_version_id,
            position_instance_id=1002,
            batch_no=self.batch.batch_no,
            requested_level_code="PT-7",
            status=AppointmentApplicationCase.Status.ELIGIBLE,
        )
        with self.assertRaises(AppointmentQuotaError) as cm:
            self.service.reserve(
                application_case_id=other_case.id, quota_pool_id=self.pool.id
            )
        self.assertEqual(cm.exception.code, "APPOINTMENT_QUOTA_EXHAUSTED")
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 1)

    def test_release_then_re_reserve_reuses_same_receipt(self):
        reservation = self.service.reserve(
            application_case_id=self.case.id, quota_pool_id=self.pool.id
        )
        released = self.service.release(reservation.id)
        self.assertEqual(released.status, AppointmentQuotaReservation.Status.RELEASED)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 0)

        again = self.service.reserve(
            application_case_id=self.case.id, quota_pool_id=self.pool.id
        )
        self.assertEqual(again.id, reservation.id)
        self.assertEqual(again.status, AppointmentQuotaReservation.Status.ACTIVE)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 1)

    def test_publicity_case_can_retry_existing_or_late_capacity_reservation(self):
        self.case.status = AppointmentApplicationCase.Status.PUBLICITY
        self.case.save(update_fields=["status", "updated_at"])

        reservation = self.service.reserve(
            application_case_id=self.case.id,
            quota_pool_id=self.pool.id,
        )

        self.assertEqual(reservation.status, AppointmentQuotaReservation.Status.ACTIVE)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 1)

    def test_consume_moves_reserved_to_occupied_once(self):
        reservation = self.service.reserve(
            application_case_id=self.case.id, quota_pool_id=self.pool.id
        )
        consumed = self.service.consume(reservation.id)
        self.assertEqual(consumed.status, AppointmentQuotaReservation.Status.CONSUMED)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 0)
        self.assertEqual(self.pool.occupied, 1)

        # Replay is idempotent and cannot double-increment occupancy.
        self.service.consume(reservation.id)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.occupied, 1)

    def test_pool_from_another_batch_is_rejected(self):
        other_batch = AppointmentBatch.objects.create(
            tenant_id=self.tenant,
            batch_no="B-2026-02",
            name="另一个批次",
            policy_version_id=uuid.uuid4(),
        )
        other_pool = AppointmentQuotaPool.objects.create(
            tenant_id=self.tenant,
            batch=other_batch,
            category_code="PROFESSIONAL_TECHNICAL",
            exact_level_code="PT-7",
            authorized=3,
        )
        with self.assertRaises(AppointmentQuotaError) as cm:
            self.service.reserve(
                application_case_id=self.case.id, quota_pool_id=other_pool.id
            )
        self.assertEqual(cm.exception.code, "APPOINTMENT_QUOTA_BATCH_MISMATCH")

    def test_exact_level_pool_cannot_be_used_for_different_requested_level(self):
        self.case.requested_level_code = "PT-6"
        self.case.save(update_fields=["requested_level_code", "updated_at"])

        with self.assertRaises(AppointmentQuotaError) as cm:
            self.service.reserve(
                application_case_id=self.case.id,
                quota_pool_id=self.pool.id,
            )

        self.assertEqual(cm.exception.code, "APPOINTMENT_QUOTA_LEVEL_MISMATCH")
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 0)

    def test_case_policy_must_match_frozen_batch_policy(self):
        self.case.policy_version_id = uuid.uuid4()
        self.case.save(update_fields=["policy_version_id", "updated_at"])

        with self.assertRaises(AppointmentQuotaError) as cm:
            self.service.reserve(
                application_case_id=self.case.id,
                quota_pool_id=self.pool.id,
            )

        self.assertEqual(cm.exception.code, "APPOINTMENT_QUOTA_POLICY_MISMATCH")
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 0)
