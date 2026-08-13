import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentPolicyVersion,
    AppointmentPositionSupplySnapshot,
    AppointmentQuotaPool,
)
from hr_appointment.services.batch_service import (
    AppointmentBatchError,
    AppointmentBatchInput,
    AppointmentBatchService,
)


class AppointmentBatchServiceTests(TestCase):
    def setUp(self):
        self.tenant = 77
        self.policy = AppointmentPolicyVersion.objects.create(
            tenant_id=self.tenant,
            policy_code="APPOINT-2026",
            name="2026 岗位聘任办法",
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        self.service = AppointmentBatchService(self.tenant, actor_user_id=9)
        self.now = timezone.now().replace(microsecond=0)

    def _draft(self, *, batch_no="B-2026-01"):
        return self.service.create_draft(
            AppointmentBatchInput(
                batch_no=batch_no,
                name="2026 专技岗位竞聘",
                policy_version_id=self.policy.id,
                target_categories=("PROFESSIONAL_TECHNICAL",),
                target_levels=("PT-7",),
                application_from=self.now - timedelta(hours=1),
                application_to=self.now + timedelta(days=5),
            )
        )

    def _supply(self, batch):
        return AppointmentPositionSupplySnapshot.objects.create(
            tenant_id=self.tenant,
            batch=batch,
            position_instance_id=1001,
            organization_id=11,
            category_code="PROFESSIONAL_TECHNICAL",
            level_code="PT-7",
            authorized_fte=1,
            occupied_fte=0,
            reserved_fte=0,
            available_fte=1,
            snapshot_at=self.now,
        )

    def _pool(self, batch, *, authorized=1):
        return AppointmentQuotaPool.objects.create(
            tenant_id=self.tenant,
            batch=batch,
            category_code="PROFESSIONAL_TECHNICAL",
            exact_level_code="PT-7",
            authorized=authorized,
        )

    def test_create_draft_requires_tenant_owned_policy_and_string_targets(self):
        foreign = AppointmentPolicyVersion.objects.create(
            tenant_id=88,
            policy_code="FOREIGN",
            name="外校办法",
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.create_draft(
                AppointmentBatchInput(
                    batch_no="B-X",
                    name="跨校批次",
                    policy_version_id=foreign.id,
                )
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_POLICY_NOT_FOUND")

        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.create_draft(
                AppointmentBatchInput(
                    batch_no="B-BAD-TARGET",
                    name="错误目标",
                    policy_version_id=self.policy.id,
                    target_categories="PROFESSIONAL_TECHNICAL",
                )
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_TARGETS_INVALID")

    def test_publish_requires_frozen_supply_and_positive_quota(self):
        batch = self._draft()
        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.publish(batch.id)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_SUPPLY_REQUIRED")

        self._supply(batch)
        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.publish(batch.id)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_QUOTA_REQUIRED")

        pool = self._pool(batch, authorized=0)
        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.publish(batch.id)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_QUOTA_EMPTY")

        pool.authorized = 1
        pool.save(update_fields=["authorized", "updated_at"])
        published = self.service.publish(batch.id)
        self.assertEqual(published.status, published.Status.PUBLISHED)

    def test_application_window_and_batch_phases_are_explicit(self):
        batch = self._draft()
        self._supply(batch)
        self._pool(batch)
        self.service.publish(batch.id)

        opened = self.service.open_applications(batch.id, now=self.now)
        self.assertEqual(opened.status, opened.Status.APPLICATION_OPEN)
        closed = self.service.close_applications(batch.id)
        self.assertEqual(closed.status, closed.Status.APPLICATION_CLOSED)
        eligibility = self.service.begin_eligibility_review(batch.id)
        self.assertEqual(eligibility.status, eligibility.Status.ELIGIBILITY_REVIEW)
        reviewing = self.service.begin_review(batch.id)
        self.assertEqual(reviewing.status, reviewing.Status.REVIEWING)

    def test_open_applications_rejects_before_or_after_frozen_window(self):
        batch = self._draft()
        self._supply(batch)
        self._pool(batch)
        self.service.publish(batch.id)

        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.open_applications(
                batch.id, now=batch.application_from - timedelta(seconds=1)
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_APPLICATION_WINDOW_NOT_STARTED")

        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.open_applications(batch.id, now=batch.application_to)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_APPLICATION_WINDOW_ENDED")

    def test_review_cannot_start_with_unresolved_eligibility_cases(self):
        batch = self._draft()
        batch.status = batch.Status.ELIGIBILITY_REVIEW
        batch.save(update_fields=["status", "updated_at"])
        case = AppointmentApplicationCase.objects.create(
            tenant_id=self.tenant,
            case_no="CASE-PENDING",
            person_id=uuid.uuid4(),
            policy_version_id=batch.policy_version_id,
            position_instance_id=1001,
            batch_no=batch.batch_no,
            requested_level_code="PT-7",
            status=AppointmentApplicationCase.Status.SUBMITTED,
        )

        with self.assertRaises(AppointmentBatchError) as ctx:
            self.service.begin_review(batch.id)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_ELIGIBILITY_INCOMPLETE")

        case.status = AppointmentApplicationCase.Status.ELIGIBLE
        case.save(update_fields=["status", "updated_at"])
        reviewing = self.service.begin_review(batch.id)
        self.assertEqual(reviewing.status, reviewing.Status.REVIEWING)
