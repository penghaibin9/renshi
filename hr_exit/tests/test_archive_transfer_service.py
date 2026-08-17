import uuid
from datetime import date
from unittest import mock

from django.test import TestCase

from hr_exit.archive_models import ArchiveTransferReceipt
from hr_exit.models import ExitCase, ExitEffect
from hr_exit.services.archive_transfer_service import (
    ArchiveTransferError,
    ArchiveTransferService,
    archive_participant_provider,
    current_received_receipt,
)
from hr_exit.services.participant_service import ExitParticipantService, ExitParticipantUnavailable


class ArchiveTransferServiceTests(TestCase):
    TENANT = 77

    def _case(self, *, tenant_id=TENANT, status=ExitCase.Status.HANDOVER):
        return ExitCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"EXIT-{uuid.uuid4().hex[:10]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.TRANSFER_OUT,
            status=status,
            requested_date=date(2026, 8, 1),
            planned_employment_end_date=date(2026, 9, 1),
        )

    def _draft(self, *, case=None, transfer_no=None, method=ArchiveTransferReceipt.TransferMethod.COURIER):
        case = case or self._case()
        kwargs = {
            "case_id": case.id,
            "transfer_no": transfer_no or f"ARCH-{uuid.uuid4().hex[:10]}",
            "destination_name": "湖南省人才档案中心",
            "transfer_method": method,
            "archive_attachment_ref": "file://archive-package-1",
        }
        if method == ArchiveTransferReceipt.TransferMethod.COURIER:
            kwargs["tracking_no"] = f"SF{uuid.uuid4().hex[:12]}"
        return ArchiveTransferService(self.TENANT, actor_user_id=9).create_transfer(**kwargs)

    def test_case_must_reach_handover_before_archive_transfer(self):
        case = self._case(status=ExitCase.Status.APPROVED)
        with self.assertRaises(ArchiveTransferError) as ctx:
            ArchiveTransferService(self.TENANT).create_transfer(
                case_id=case.id,
                transfer_no="ARCH-BLOCKED-1",
                destination_name="人才档案中心",
                transfer_method=ArchiveTransferReceipt.TransferMethod.SYSTEM_TRANSFER,
            )
        self.assertEqual(ctx.exception.code, "ARCHIVE_TRANSFER_CASE_NOT_READY")

    def test_courier_requires_tracking_no(self):
        case = self._case()
        with self.assertRaises(ArchiveTransferError) as ctx:
            ArchiveTransferService(self.TENANT).create_transfer(
                case_id=case.id,
                transfer_no="ARCH-TRACK-1",
                destination_name="人才档案中心",
                transfer_method=ArchiveTransferReceipt.TransferMethod.COURIER,
            )
        self.assertEqual(ctx.exception.code, "ARCHIVE_TRANSFER_TRACKING_REQUIRED")

    def test_send_requires_archive_evidence_and_event_failure_rolls_back(self):
        case = self._case()
        svc = ArchiveTransferService(self.TENANT, actor_user_id=9)
        receipt = svc.create_transfer(
            case_id=case.id,
            transfer_no="ARCH-SEND-1",
            destination_name="人才档案中心",
            transfer_method=ArchiveTransferReceipt.TransferMethod.SYSTEM_TRANSFER,
        )
        with self.assertRaises(ArchiveTransferError) as ctx:
            svc.mark_sent(receipt_id=receipt.id)
        self.assertEqual(ctx.exception.code, "ARCHIVE_TRANSFER_EVIDENCE_REQUIRED")

        with mock.patch(
            "hr_exit.services.archive_transfer_service.emit_registered_event",
            side_effect=RuntimeError("outbox unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
                svc.mark_sent(
                    receipt_id=receipt.id,
                    archive_attachment_ref="file://archive-package-1",
                )
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, ArchiveTransferReceipt.Status.DRAFT)
        self.assertIsNone(receipt.sent_at)

    def test_receive_requires_receiver_and_receipt_evidence(self):
        svc = ArchiveTransferService(self.TENANT, actor_user_id=9)
        receipt = self._draft()
        svc.mark_sent(receipt_id=receipt.id)

        with self.assertRaises(ArchiveTransferError) as ctx:
            svc.acknowledge_received(
                receipt_id=receipt.id,
                received_by="",
                receipt_attachment_ref="file://receipt-1",
            )
        self.assertEqual(ctx.exception.code, "ARCHIVE_TRANSFER_RECEIPT_EVIDENCE_REQUIRED")

        received = svc.acknowledge_received(
            receipt_id=receipt.id,
            received_by="档案中心 李老师",
            receipt_attachment_ref="file://receipt-1",
        )
        self.assertEqual(received.status, ArchiveTransferReceipt.Status.RECEIVED)
        self.assertIsNotNone(received.received_at)

    def test_received_is_terminal_and_returned_is_distinct(self):
        svc = ArchiveTransferService(self.TENANT, actor_user_id=9)
        received = self._draft(transfer_no="ARCH-RECEIVED-1")
        svc.mark_sent(receipt_id=received.id)
        received = svc.acknowledge_received(
            receipt_id=received.id,
            received_by="档案中心",
            receipt_attachment_ref="file://received-evidence",
        )
        received.destination_name = "篡改目标"
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            received.save()

        returned = self._draft(transfer_no="ARCH-RETURNED-1")
        svc.mark_sent(receipt_id=returned.id)
        returned = svc.mark_returned(
            receipt_id=returned.id,
            reason="材料缺页",
            receipt_attachment_ref="file://return-evidence",
        )
        self.assertEqual(returned.status, ArchiveTransferReceipt.Status.RETURNED)
        self.assertNotEqual(returned.status, ArchiveTransferReceipt.Status.RECEIVED)
        self.assertEqual(returned.return_reason, "材料缺页")

    def test_cross_tenant_receipt_is_fail_closed(self):
        case = self._case()
        receipt = self._draft(case=case)
        with self.assertRaises(ArchiveTransferError) as ctx:
            ArchiveTransferService(88).mark_sent(receipt_id=receipt.id)
        self.assertEqual(ctx.exception.code, "ARCHIVE_TRANSFER_NOT_FOUND")

    def test_superseding_receipt_replaces_old_received_receipt_for_projection(self):
        svc = ArchiveTransferService(self.TENANT, actor_user_id=9)
        case = self._case()
        old = self._draft(case=case, transfer_no="ARCH-OLD-1")
        svc.mark_sent(receipt_id=old.id)
        old = svc.acknowledge_received(
            receipt_id=old.id,
            received_by="旧接收方",
            receipt_attachment_ref="file://old-receipt",
        )
        replacement = svc.create_transfer(
            case_id=case.id,
            transfer_no="ARCH-NEW-1",
            destination_name="新档案中心",
            transfer_method=ArchiveTransferReceipt.TransferMethod.SYSTEM_TRANSFER,
            archive_attachment_ref="file://new-package",
            supersedes_receipt_id=old.id,
        )
        self.assertIsNone(current_received_receipt(tenant_id=self.TENANT, case_id=case.id))
        svc.mark_sent(receipt_id=replacement.id)
        replacement = svc.acknowledge_received(
            receipt_id=replacement.id,
            received_by="新接收方",
            receipt_attachment_ref="file://new-receipt",
        )
        current = current_received_receipt(tenant_id=self.TENANT, case_id=case.id)
        self.assertEqual(current.id, replacement.id)


class ArchiveParticipantProviderTests(TestCase):
    TENANT = 77

    def _case_and_effect(self):
        case = ExitCase.objects.create(
            tenant_id=self.TENANT,
            case_no=f"EXIT-{uuid.uuid4().hex[:10]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.TRANSFER_OUT,
            status=ExitCase.Status.EFFECTIVE,
            planned_employment_end_date=date(2026, 9, 1),
        )
        effect = ExitEffect.objects.create(
            tenant_id=self.TENANT,
            case_id=case.id,
            effect_version=1,
            idempotency_key=f"IDEM-{uuid.uuid4().hex}",
            status=ExitEffect.Status.PENDING,
            hr03_status=ExitEffect.ParticipantStatus.SUCCESS,
            hr14_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            iam_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            settlement_status=ExitEffect.ParticipantStatus.NOT_REQUIRED,
            archive_status=ExitEffect.ParticipantStatus.PENDING,
        )
        return case, effect

    def test_provider_is_unavailable_until_formal_received_receipt_exists(self):
        case, effect = self._case_and_effect()
        with self.assertRaises(ExitParticipantUnavailable):
            archive_participant_provider(
                tenant_id=self.TENANT,
                case=case,
                effect=effect,
                actor_user_id=9,
            )

    def test_builtin_archive_provider_completes_existing_saga(self):
        case, effect = self._case_and_effect()
        svc = ArchiveTransferService(self.TENANT, actor_user_id=9)
        receipt = svc.create_transfer(
            case_id=case.id,
            transfer_no="ARCH-SAGA-1",
            destination_name="省人才档案中心",
            transfer_method=ArchiveTransferReceipt.TransferMethod.SYSTEM_TRANSFER,
            archive_attachment_ref="file://saga-package",
        )
        svc.mark_sent(receipt_id=receipt.id)
        svc.acknowledge_received(
            receipt_id=receipt.id,
            received_by="省人才档案中心",
            receipt_attachment_ref="file://saga-receipt",
        )

        result = ExitParticipantService(self.TENANT, actor_user_id=9).execute(
            effect_id=effect.id,
            participant="ARCHIVE",
        )
        self.assertEqual(result.status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(result.receipt["receiptId"], str(receipt.id))
        effect.refresh_from_db()
        self.assertEqual(effect.archive_status, ExitEffect.ParticipantStatus.SUCCESS)
        self.assertEqual(effect.status, ExitEffect.Status.SUCCESS)