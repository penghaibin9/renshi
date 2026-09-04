import json
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from hr_exit import archive_api
from hr_exit.archive_registry import PERM_ARCHIVE_MANAGE, PERM_ARCHIVE_VIEW


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class Hr16ArchiveApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.case_id = uuid.uuid4()
        self.receipt_id = uuid.uuid4()

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    def test_view_permission_cannot_create_archive_transfer(self, _allowed, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/exit/cases/{self.case_id}/archive-transfers/",
            data=json.dumps(
                {
                    "transferNo": "ARCH-1",
                    "destinationName": "省人才档案中心",
                    "transferMethod": "SYSTEM_TRANSFER",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({PERM_ARCHIVE_VIEW})

        response = archive_api.case_archive_transfers(request, self.case_id)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"PERMISSION_DENIED", response.content)
        self.assertIn(PERM_ARCHIVE_MANAGE.encode(), response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.archive_api.ArchiveTransferService")
    def test_create_uses_resolved_tenant_actor_and_canonical_payload(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.create_transfer.return_value = SimpleNamespace(
            id=self.receipt_id,
            transfer_no="ARCH-2",
            case_id=self.case_id,
            person_id=uuid.uuid4(),
            destination_type="PERSONNEL_ARCHIVE",
            destination_name="省人才档案中心",
            destination_address="长沙市",
            transfer_method="COURIER",
            tracking_no="SF123",
            archive_attachment_ref="file:package",
            receipt_attachment_ref="",
            operator_user_id=88,
            sent_at=None,
            received_at=None,
            received_by="",
            return_reason="",
            status="DRAFT",
            supersedes_receipt_id=None,
        )
        request = self.factory.post(
            f"/api/v1/hr/exit/cases/{self.case_id}/archive-transfers/",
            data=json.dumps(
                {
                    "transferNo": "ARCH-2",
                    "destinationType": "PERSONNEL_ARCHIVE",
                    "destinationName": "省人才档案中心",
                    "destinationAddress": "长沙市",
                    "transferMethod": "COURIER",
                    "trackingNo": "SF123",
                    "archiveAttachmentRef": "file:package",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub({PERM_ARCHIVE_MANAGE})

        response = archive_api.case_archive_transfers(request, self.case_id)

        self.assertEqual(response.status_code, 201)
        service_cls.assert_called_once_with(7, actor_user_id=88)
        service_cls.return_value.create_transfer.assert_called_once_with(
            case_id=self.case_id,
            transfer_no="ARCH-2",
            destination_name="省人才档案中心",
            destination_type="PERSONNEL_ARCHIVE",
            destination_address="长沙市",
            transfer_method="COURIER",
            tracking_no="SF123",
            archive_attachment_ref="file:package",
            supersedes_receipt_id=None,
        )
        self.assertIn(b'"status": "DRAFT"', response.content)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.archive_api.ArchiveTransferService")
    def test_receive_preserves_receiver_and_receipt_evidence(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.acknowledge_received.return_value = SimpleNamespace(
            id=self.receipt_id,
            transfer_no="ARCH-3",
            case_id=self.case_id,
            person_id=uuid.uuid4(),
            destination_type="",
            destination_name="档案中心",
            destination_address="",
            transfer_method="SYSTEM_TRANSFER",
            tracking_no="",
            archive_attachment_ref="file:package",
            receipt_attachment_ref="file:receipt",
            operator_user_id=88,
            sent_at=None,
            received_at=None,
            received_by="李老师",
            return_reason="",
            status="RECEIVED",
            supersedes_receipt_id=None,
        )
        request = self.factory.post(
            f"/api/v1/hr/exit/archive-transfers/{self.receipt_id}/receive/",
            data=json.dumps(
                {"receivedBy": "李老师", "receiptAttachmentRef": "file:receipt"}
            ),
            content_type="application/json",
        )
        request.user = UserStub({PERM_ARCHIVE_MANAGE})

        response = archive_api.receive_archive_transfer(request, self.receipt_id)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.acknowledge_received.assert_called_once_with(
            receipt_id=self.receipt_id,
            received_by="李老师",
            receipt_attachment_ref="file:receipt",
        )
        self.assertIn(b"RECEIVED", response.content)

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.archive_api.save_evidence", return_value=("storage://receipt.pdf", "receipt.pdf"))
    @patch("hr_exit.archive_api.ArchiveTransferService")
    def test_receive_accepts_uploaded_receipt_evidence(
        self, service_cls, save_evidence, _allowed, _tenant
    ):
        service_cls.return_value.acknowledge_received.return_value = SimpleNamespace(
            id=self.receipt_id,
            transfer_no="ARCH-4",
            case_id=self.case_id,
            person_id=uuid.uuid4(),
            destination_type="",
            destination_name="档案中心",
            destination_address="",
            transfer_method="SYSTEM_TRANSFER",
            tracking_no="",
            archive_attachment_ref="storage://package.pdf",
            receipt_attachment_ref="storage://receipt.pdf",
            operator_user_id=88,
            sent_at=None,
            received_at=None,
            received_by="李老师",
            return_reason="",
            status="RECEIVED",
            supersedes_receipt_id=None,
        )
        upload = SimpleUploadedFile("receipt.pdf", b"receipt", content_type="application/pdf")
        request = self.factory.post(
            f"/api/v1/hr/exit/archive-transfers/{self.receipt_id}/receive/",
            data={"receivedBy": "李老师", "file": upload},
        )
        request.user = UserStub({PERM_ARCHIVE_MANAGE})

        response = archive_api.receive_archive_transfer(request, self.receipt_id)

        self.assertEqual(response.status_code, 200)
        save_evidence.assert_called_once()
        service_cls.return_value.acknowledge_received.assert_called_once_with(
            receipt_id=self.receipt_id,
            received_by="李老师",
            receipt_attachment_ref="storage://receipt.pdf",
        )

    def test_non_supported_method_is_rejected(self):
        request = self.factory.delete(
            f"/api/v1/hr/exit/archive-transfers/{self.receipt_id}/send/"
        )
        request.user = UserStub({PERM_ARCHIVE_MANAGE})
        response = archive_api.send_archive_transfer(request, self.receipt_id)
        self.assertEqual(response.status_code, 405)

    def test_private_storage_refs_are_not_returned(self):
        receipt = SimpleNamespace(
            id=self.receipt_id,
            transfer_no="ARCH-PRIVATE",
            case_id=self.case_id,
            person_id=uuid.uuid4(),
            destination_type="PERSONNEL_ARCHIVE",
            destination_name="省人才档案中心",
            destination_address="",
            transfer_method="SYSTEM_TRANSFER",
            tracking_no="",
            archive_attachment_ref=(
                "storage://protected/hr16/7/archive-package/a-package.pdf"
            ),
            receipt_attachment_ref=(
                "storage://protected/hr16/7/archive-receipt/b-receipt.pdf"
            ),
            operator_user_id=88,
            sent_at=None,
            received_at=None,
            received_by="",
            return_reason="",
            status="RECEIVED",
            supersedes_receipt_id=None,
            evidence_ref="storage://protected/hr16/7/archive-receipt/b-receipt.pdf",
            content_hash="a" * 64,
            sealed_at=None,
        )

        data = archive_api._data(receipt)

        self.assertEqual(data["archiveAttachmentRef"], "")
        self.assertEqual(data["receiptAttachmentRef"], "")
        self.assertEqual(data["evidenceRef"], "")
        self.assertTrue(data["archiveAttachment"]["available"])
        self.assertTrue(data["receiptAttachment"]["available"])

    @patch("hr_exit.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_exit.api.get_allowed_company_ids", return_value={7})
    @patch("hr_exit.archive_api.HrExitEvidenceAccessAudit.objects.create")
    @patch("hr_exit.archive_api.open_evidence")
    @patch("hr_exit.archive_api.ArchiveTransferReceipt.objects.filter")
    def test_archive_attachment_download_is_tenant_scoped_and_audited(
        self, filter_receipts, open_evidence, create_audit, _allowed, _tenant
    ):
        filter_receipts.return_value.first.return_value = SimpleNamespace(
            id=self.receipt_id,
            archive_attachment_ref=(
                "storage://protected/hr16/7/archive-package/a-package.pdf"
            ),
            receipt_attachment_ref="",
        )
        open_evidence.return_value = (
            BytesIO(b"package"),
            "package.pdf",
            "application/pdf",
            "b" * 64,
        )
        request = self.factory.get(
            f"/api/v1/hr/exit/archive-transfers/{self.receipt_id}/attachments/package/download/",
            HTTP_X_HR_ACCESS_REASON="档案转递复核",
        )
        request.user = UserStub({PERM_ARCHIVE_VIEW})

        response = archive_api.download_archive_attachment(
            request, self.receipt_id, "package"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        filter_receipts.assert_called_once_with(tenant_id=7, id=self.receipt_id)
        self.assertEqual(create_audit.call_args.kwargs["purpose"], "档案转递复核")
        self.assertEqual(create_audit.call_args.kwargs["evidence_role"], "ARCHIVE_PACKAGE")
