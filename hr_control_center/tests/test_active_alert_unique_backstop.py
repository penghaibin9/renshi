from pathlib import Path

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from hr_control_center.models import HrAlertInstance


class ActiveAlertUniqueBackstopTests(TestCase):
    def _create(self, *, status, suffix=""):
        now = timezone.now()
        return HrAlertInstance.objects.create(
            tenant_id=7101,
            alert_key="contract.expire_90d",
            source_domain="contract",
            source_object_type="employee",
            source_object_id=f"E-1{suffix}",
            dedupe_key="contract.expire_90d:employee:E-1:2026-12-01",
            title="Contract expiry",
            severity=HrAlertInstance.Severity.HIGH,
            status=status,
            first_seen_at=now,
            last_seen_at=now,
        )

    def test_different_active_statuses_still_collide(self):
        self._create(status=HrAlertInstance.Status.OPEN)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(status=HrAlertInstance.Status.ACKNOWLEDGED, suffix="-duplicate")

    def test_terminal_history_does_not_block_new_active_instance(self):
        self._create(status=HrAlertInstance.Status.RESOLVED)
        active = self._create(status=HrAlertInstance.Status.OPEN, suffix="-new")

        self.assertEqual(active.status, HrAlertInstance.Status.OPEN)


class ActiveAlertMigrationContractTests(TestCase):
    def test_mysql_uses_generated_guard_and_unique_index(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0003_active_alert_unique_backstop.py"
        )
        source = migration_path.read_text(encoding="utf-8")

        self.assertIn("GENERATED ALWAYS AS", source)
        self.assertIn("CREATE UNIQUE INDEX", source)
        self.assertIn("active_dedupe_guard", source)
        self.assertIn("atomic = False", source)
