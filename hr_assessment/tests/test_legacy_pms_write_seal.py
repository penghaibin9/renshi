from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import TestCase

from hr_assessment.legacy.write_seal import (
    is_pms_write_frozen,
    set_pms_write_frozen,
)
from hr_assessment.models.legacy import HrLegacyPmsWriterSealEvent
from pms.models import Period


class LegacyPmsWriteSealTests(TestCase):
    def tearDown(self):
        set_pms_write_frozen(frozen=False, reason="test cleanup", operator="TEST")

    def test_freeze_blocks_real_pms_create_update_delete_and_unfreeze_restores_writer(self):
        period = Period.objects.create(
            period_name="legacy-seal-before-freeze",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

        seal = set_pms_write_frozen(
            frozen=True,
            reason="HR12 authority cutover",
            operator="cutover-test",
        )
        self.assertTrue(is_pms_write_frozen())
        self.assertEqual(seal.revision, 1)

        with self.assertRaisesRegex(PermissionDenied, "LEGACY_PMS_WRITE_FROZEN"):
            with transaction.atomic():
                Period.objects.create(
                    period_name="must-not-be-created",
                    start_date=date(2027, 1, 1),
                    end_date=date(2027, 12, 31),
                )

        period.period_name = "must-not-be-updated"
        with self.assertRaisesRegex(PermissionDenied, "LEGACY_PMS_WRITE_FROZEN"):
            with transaction.atomic():
                period.save()

        with self.assertRaisesRegex(PermissionDenied, "LEGACY_PMS_WRITE_FROZEN"):
            with transaction.atomic():
                period.delete()

        seal = set_pms_write_frozen(
            frozen=False,
            reason="rollback rehearsal",
            operator="cutover-test",
        )
        self.assertFalse(is_pms_write_frozen())
        self.assertEqual(seal.revision, 2)

        period.period_name = "legacy-seal-after-unfreeze"
        period.save()
        self.assertTrue(Period.objects.filter(pk=period.pk).exists())

        self.assertEqual(
            list(HrLegacyPmsWriterSealEvent.objects.values_list("action", flat=True)),
            ["UNFREEZE", "FREEZE"],
        )
