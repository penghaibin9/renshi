import uuid
from datetime import date
from pathlib import Path

from django.db import transaction
from django.test import SimpleTestCase, TestCase

from hr_exit.archive_models import ArchiveTransferReceipt
from hr_exit.archive_registry import (
    EVENT_RETIREMENT_PENSION_STATUS_CHANGED,
    PERM_RETIREMENT_PENSION_MANAGE,
)
from hr_exit.models import ExitCase, RetirementFact, RetirementPensionTransition
from hr_exit.services.archive_transfer_service import ArchiveTransferService


class Hr16RemainingSealContractTests(SimpleTestCase):
    def test_permission_event_and_mysql_seals_are_declared(self):
        self.assertEqual(PERM_RETIREMENT_PENSION_MANAGE, "hr.exit.retirement.pension.manage")
        self.assertEqual(
            EVENT_RETIREMENT_PENSION_STATUS_CHANGED,
            "hr.exit.retirement.pension_status_changed",
        )
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0011_retirement_archive_integrity.py"
        ).read_text(encoding="utf-8")
        for trigger in (
            "hr16_retirement_fact_guard_update",
            "hr16_retirement_fact_no_delete",
            "hr16_archive_receipt_no_update",
            "hr16_archive_receipt_no_delete",
            "hr16_pension_transition_no_update",
            "hr16_pension_transition_no_delete",
        ):
            self.assertIn(f"CREATE TRIGGER {trigger}", migration)
        self.assertIn("RETIREMENT_PENSION_STATUS_INVALID_TRANSITION", migration)
        self.assertIn("SIGNAL SQLSTATE '45000'", migration)


class ArchiveReceiptIntegrityTests(TestCase):
    def _received(self):
        case = ExitCase.objects.create(
            tenant_id=77,
            case_no=f"EXIT-{uuid.uuid4().hex[:10]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.TRANSFER_OUT,
            status=ExitCase.Status.HANDOVER,
            planned_employment_end_date=date(2026, 9, 1),
        )
        service = ArchiveTransferService(77, actor_user_id=9)
        receipt = service.create_transfer(
            case_id=case.id,
            transfer_no=f"ARCH-{uuid.uuid4().hex[:10]}",
            destination_name="省人才档案中心",
            transfer_method=ArchiveTransferReceipt.TransferMethod.SYSTEM_TRANSFER,
            archive_attachment_ref="file://archive-package",
        )
        service.mark_sent(receipt_id=receipt.id)
        return service.acknowledge_received(
            receipt_id=receipt.id,
            received_by="省人才档案中心",
            receipt_attachment_ref="file://signed-receipt",
        )

    def test_terminal_receipt_is_hashed_and_all_orm_mutation_paths_fail_closed(self):
        receipt = self._received()
        self.assertEqual(receipt.content_hash, receipt.calculate_content_hash())
        self.assertTrue(receipt.evidence_ref)
        self.assertIsNotNone(receipt.sealed_at)
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            with transaction.atomic():
                ArchiveTransferReceipt.objects.filter(pk=receipt.pk).update(
                    destination_name="tampered"
                )
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            with transaction.atomic():
                ArchiveTransferReceipt.objects.bulk_update(
                    [receipt], ["destination_name"]
                )
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            with transaction.atomic():
                ArchiveTransferReceipt.objects.filter(pk=receipt.pk).delete()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            with transaction.atomic():
                receipt.delete()


class RetirementModelSealTests(SimpleTestCase):
    def test_formal_hash_excludes_pension_progress_but_covers_identity_and_dates(self):
        fact = RetirementFact(
            tenant_id=77,
            fact_no="RET-HASH-001",
            person_id=uuid.uuid4(),
            exit_fact_id=uuid.uuid4(),
            retirement_type="STATUTORY",
            statutory_date=date(2026, 9, 1),
            effective_date=date(2026, 9, 1),
            evidence_ref="exitfact://formal-source",
            sealed_at=date(2026, 8, 30),
            created_by=9,
        )
        original = fact.calculate_content_hash()
        fact.pension_processing_status = RetirementFact.PensionStatus.IN_PROGRESS
        self.assertEqual(original, fact.calculate_content_hash())
        fact.effective_date = date(2026, 9, 2)
        self.assertNotEqual(original, fact.calculate_content_hash())

    def test_pension_transition_hash_covers_status_and_evidence(self):
        transition = RetirementPensionTransition(
            tenant_id=77,
            retirement_fact_id=uuid.uuid4(),
            from_status=RetirementFact.PensionStatus.NOT_STARTED,
            to_status=RetirementFact.PensionStatus.IN_PROGRESS,
            evidence_ref="receipt://pension/001",
            sealed_at=date(2026, 8, 30),
            created_by=9,
        )
        first = transition.calculate_content_hash()
        transition.evidence_ref = "receipt://pension/002"
        self.assertNotEqual(first, transition.calculate_content_hash())
