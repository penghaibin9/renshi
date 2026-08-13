import uuid
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import (
    AppointmentPolicyVersion,
    AppointmentPositionSupplySnapshot,
    AppointmentQuotaPool,
)
from hr_appointment.population_models import (
    AppointmentPopulationMemberSnapshot,
    AppointmentPopulationSnapshot,
)
from hr_appointment.services.batch_service import AppointmentBatchInput, AppointmentBatchService


class AppointmentBatchFreezeGuardTests(TestCase):
    def setUp(self):
        self.tenant = 77
        self.now = timezone.now().replace(microsecond=0)
        self.policy = AppointmentPolicyVersion.objects.create(
            tenant_id=self.tenant,
            policy_code="FREEZE-2026",
            name="2026 冻结规则",
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        self.service = AppointmentBatchService(self.tenant, actor_user_id=9)
        self.batch = self.service.create_draft(
            AppointmentBatchInput(
                batch_no="B-FREEZE-01",
                name="冻结合同批次",
                policy_version_id=self.policy.id,
                target_categories=("PROFESSIONAL_TECHNICAL",),
                target_levels=("PT-7",),
                application_from=self.now - timedelta(hours=1),
                application_to=self.now + timedelta(days=5),
                publicity_from=self.now + timedelta(days=10),
                publicity_to=self.now + timedelta(days=15),
            )
        )
        self.population = AppointmentPopulationSnapshot.objects.create(
            tenant_id=self.tenant,
            batch=self.batch,
            as_of_date=self.now.date(),
            snapshot_at=self.now,
            member_count=1,
            content_hash="a" * 64,
        )
        self.population_member = AppointmentPopulationMemberSnapshot.objects.create(
            tenant_id=self.tenant,
            snapshot=self.population,
            person_id=uuid.uuid4(),
            staff_id=uuid.uuid4(),
            member_hash="b" * 64,
        )
        self.supply = AppointmentPositionSupplySnapshot.objects.create(
            tenant_id=self.tenant,
            batch=self.batch,
            position_instance_id=1001,
            organization_id=11,
            category_code="PROFESSIONAL_TECHNICAL",
            level_code="PT-7",
            authorized_fte=1,
            occupied_fte=0,
            reserved_fte=0,
            available_fte=1,
            snapshot_at=self.now,
            source_version="hr02-v1",
            source_hash="a" * 64,
        )
        self.pool = AppointmentQuotaPool.objects.create(
            tenant_id=self.tenant,
            batch=self.batch,
            category_code="PROFESSIONAL_TECHNICAL",
            exact_level_code="PT-7",
            authorized=1,
        )

    def test_supply_snapshot_is_immutable_after_capture(self):
        self.supply.available_fte = 2
        with self.assertRaises(ValidationError) as ctx:
            self.supply.save(update_fields=["available_fte", "updated_at"])
        self.assertIn("APPOINTMENT_SUPPLY_SNAPSHOT_IMMUTABLE", str(ctx.exception))

        self.supply.refresh_from_db()
        self.assertEqual(self.supply.available_fte, 1)

    def test_quota_basis_can_be_corrected_before_publish(self):
        self.pool.authorized = 2
        self.pool.exception_quota = 1
        self.pool.save(update_fields=["authorized", "exception_quota", "updated_at"])

        self.pool.refresh_from_db()
        self.assertEqual(self.pool.authorized, 2)
        self.assertEqual(self.pool.exception_quota, 1)

    def test_published_batch_policy_and_quota_basis_are_immutable(self):
        self.service.publish(self.batch.id)

        self.batch.refresh_from_db()
        self.batch.name = "静默改名"
        with self.assertRaises(ValidationError) as ctx:
            self.batch.save(update_fields=["name", "updated_at"])
        self.assertIn("APPOINTMENT_BATCH_FROZEN", str(ctx.exception))

        self.policy.refresh_from_db()
        self.policy.name = "静默改制度"
        with self.assertRaises(ValidationError) as ctx:
            self.policy.save(update_fields=["name", "updated_at"])
        self.assertIn("APPOINTMENT_POLICY_VERSION_FROZEN", str(ctx.exception))

        self.pool.refresh_from_db()
        self.pool.authorized = 2
        with self.assertRaises(ValidationError) as ctx:
            self.pool.save(update_fields=["authorized", "updated_at"])
        self.assertIn("APPOINTMENT_QUOTA_BASIS_IMMUTABLE", str(ctx.exception))

    def test_published_quota_runtime_counters_remain_mutable(self):
        self.service.publish(self.batch.id)
        self.pool.refresh_from_db()
        self.pool.reserved = 1
        self.pool.version += 1
        self.pool.save(update_fields=["reserved", "version", "updated_at"])

        self.pool.refresh_from_db()
        self.assertEqual(self.pool.reserved, 1)
        self.assertEqual(self.pool.available, 0)

    def test_published_frozen_inputs_cannot_be_deleted(self):
        self.service.publish(self.batch.id)

        with self.assertRaises(ValidationError) as ctx:
            self.supply.delete()
        self.assertIn("APPOINTMENT_SUPPLY_SNAPSHOT_IMMUTABLE", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            self.pool.delete()
        self.assertIn("APPOINTMENT_QUOTA_BASIS_IMMUTABLE", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            self.population_member.delete()
        self.assertIn("APPOINTMENT_POPULATION_MEMBER_IMMUTABLE", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            self.policy.delete()
        self.assertIn("APPOINTMENT_POLICY_VERSION_IN_USE", str(ctx.exception))
