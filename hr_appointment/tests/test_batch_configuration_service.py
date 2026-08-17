import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from hr_appointment.models import AppointmentBatch, AppointmentPolicyVersion
from hr_appointment.services.batch_configuration_service import (
    AppointmentBatchConfigurationError,
    AppointmentBatchConfigurationService,
    AppointmentBatchPatch,
)


class AppointmentBatchConfigurationServiceTests(TestCase):
    def setUp(self):
        self.tenant = 77
        self.now = timezone.now().replace(microsecond=0)
        self.policy = AppointmentPolicyVersion.objects.create(
            tenant_id=self.tenant,
            policy_code="PATCH-1",
            name="原制度",
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        self.other_policy = AppointmentPolicyVersion.objects.create(
            tenant_id=self.tenant,
            policy_code="PATCH-2",
            name="新制度",
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        self.batch = AppointmentBatch.objects.create(
            tenant_id=self.tenant,
            batch_no="B-PATCH-01",
            name="待配置批次",
            policy_version_id=self.policy.id,
            status=AppointmentBatch.Status.DRAFT,
        )
        self.service = AppointmentBatchConfigurationService(self.tenant, actor_user_id=9)

    def test_patch_completes_draft_and_advances_optimistic_version(self):
        updated = self.service.update_draft(
            self.batch.id,
            expected_version=1,
            patch=AppointmentBatchPatch(
                name="2026 专技岗位竞聘",
                policy_version_id=self.other_policy.id,
                target_categories=["PROFESSIONAL_TECHNICAL"],
                target_levels=["PT-7"],
                application_from=self.now,
                application_to=self.now + timedelta(days=5),
                publicity_from=self.now + timedelta(days=10),
                publicity_to=self.now + timedelta(days=15),
            ),
        )

        self.assertEqual(updated.status, AppointmentBatch.Status.CONFIGURING)
        self.assertEqual(updated.version_no, 2)
        self.assertEqual(updated.policy_version_id, self.other_policy.id)
        self.assertEqual(updated.target_levels_json, ["PT-7"])
        self.assertEqual(updated.publicity_to, self.now + timedelta(days=15))

    def test_stale_expected_version_fails_without_overwriting_newer_config(self):
        self.batch.version_no = 2
        self.batch.name = "较新配置"
        self.batch.save(update_fields=["version_no", "name", "updated_at"])

        with self.assertRaises(AppointmentBatchConfigurationError) as ctx:
            self.service.update_draft(
                self.batch.id,
                expected_version=1,
                patch=AppointmentBatchPatch(name="旧客户端覆盖"),
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_VERSION_CONFLICT")
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.name, "较新配置")

    def test_published_batch_cannot_be_patched(self):
        self.batch.status = AppointmentBatch.Status.PUBLISHED
        self.batch.save(update_fields=["status", "updated_at"])

        with self.assertRaises(AppointmentBatchConfigurationError) as ctx:
            self.service.update_draft(
                self.batch.id,
                expected_version=1,
                patch=AppointmentBatchPatch(name="发布后改名"),
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_BATCH_FROZEN")

    def test_cross_tenant_policy_is_rejected(self):
        foreign = AppointmentPolicyVersion.objects.create(
            tenant_id=88,
            policy_code="FOREIGN",
            name="外校制度",
            version_no=1,
            effective_from=date(2026, 1, 1),
        )
        with self.assertRaises(AppointmentBatchConfigurationError) as ctx:
            self.service.update_draft(
                self.batch.id,
                expected_version=1,
                patch=AppointmentBatchPatch(policy_version_id=foreign.id),
            )
        self.assertEqual(ctx.exception.code, "APPOINTMENT_POLICY_NOT_FOUND")
