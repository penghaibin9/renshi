from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from hr_contracts.models import (
    HrAgreementDocument,
    HrContractAgreement,
    HrContractAuditEvent,
    HrContractDownloadTicket,
    HrContractVersion,
)
from hr_contracts.services.document_binding import bind_signed_document_reference
from hr_contracts.services.document_storage import (
    ContractDocumentStorageError,
    open_contract_document,
    store_contract_document,
)
from hr_contracts.services.document_ticket import (
    ContractDocumentTicketError,
    DownloadTicketService,
)


@override_settings(MALWARE_SCAN_REQUIRED=False, MALWARE_SCAN_MAX_BYTES=50 * 1024 * 1024)
class ContractDocumentStorageTests(SimpleTestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.media.cleanup()

    def test_pdf_is_partitioned_hashed_and_opened_without_media_url(self):
        agreement_id = uuid.uuid4()
        stored = store_contract_document(
            SimpleUploadedFile(
                "劳动合同.pdf", b"%PDF-1.7\ncontract", content_type="application/pdf"
            ),
            tenant_id=7,
            agreement_id=agreement_id,
        )
        self.assertTrue(
            stored["file_path"].startswith(
                f"hr_contracts_private/7/{agreement_id}/"
            )
        )
        self.assertLessEqual(len(stored["file_path"]), 255)
        self.assertEqual(
            HrAgreementDocument._meta.get_field("file_path").max_length,
            255,
        )
        self.assertEqual(len(stored["sha256"]), 64)
        stream = open_contract_document(
            stored["file_path"], tenant_id=7, agreement_id=agreement_id
        )
        self.assertEqual(stream.read(), b"%PDF-1.7\ncontract")
        stream.close()

    def test_extension_mime_and_magic_bytes_must_all_match(self):
        cases = (
            SimpleUploadedFile("contract.exe", b"MZ", content_type="application/pdf"),
            SimpleUploadedFile("contract.pdf", b"<html>", content_type="application/pdf"),
            SimpleUploadedFile("contract.pdf", b"%PDF-1.7", content_type="text/html"),
        )
        for upload in cases:
            with self.subTest(name=upload.name):
                with self.assertRaises(ContractDocumentStorageError):
                    store_contract_document(
                        upload, tenant_id=7, agreement_id=uuid.uuid4()
                    )

    def test_wrong_tenant_or_traversal_storage_key_is_rejected(self):
        agreement_id = uuid.uuid4()
        for key in (
            f"hr_contracts_private/8/{agreement_id}/file.pdf",
            f"hr_contracts_private/7/{agreement_id}/../file.pdf",
            f"hr_contracts_private\\7\\{agreement_id}\\file.pdf",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ContractDocumentStorageError):
                    open_contract_document(
                        key, tenant_id=7, agreement_id=agreement_id
                    )

    def test_http_contract_never_places_ticket_in_url(self):
        source = (
            Path(__file__).resolve().parents[1] / "api" / "documents.py"
        ).read_text(encoding="utf-8")
        routes = (Path(__file__).resolve().parents[1] / "api_urls.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"ticketHeader": "X-HR-Download-Ticket"', source)
        self.assertIn('request.headers.get("X-HR-Download-Ticket"', source)
        self.assertNotIn("<str:ticket>", routes)
        self.assertIn("enforce_contract_permission", source)
        self.assertIn("resolve_contract_tenant", source)


class ContractDocumentTicketTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.media = tempfile.TemporaryDirectory(prefix="hr07-document-tests-")
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.agreement = HrContractAgreement.objects.create(
            tenant_id=7,
            agreement_no="HT-2026-0001",
            staff_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            agreement_title="教师聘用合同",
            agreement_type="FIXED_TERM",
        )
        stored = store_contract_document(
            SimpleUploadedFile(
                "教师聘用合同.pdf",
                b"%PDF-1.7\ncontract",
                content_type="application/pdf",
            ),
            tenant_id=7,
            agreement_id=self.agreement.id,
        )
        self.document = HrAgreementDocument.objects.create(
            tenant_id=7,
            agreement=self.agreement,
            document_type=HrAgreementDocument.DocumentType.SIGNED_CONTRACT,
            signature_status=HrAgreementDocument.SignatureStatus.PENDING,
            created_by=31,
            updated_by=31,
            **stored,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media.cleanup()

    def test_ticket_is_hashed_actor_bound_audited_and_single_use(self):
        service = DownloadTicketService(7)
        token, ticket = service.generate_ticket(
            self.document.id,
            actor_id=31,
            purpose="合同归档复核",
            request_id="req-1",
        )
        self.assertNotEqual(ticket.token_hash, token)
        self.assertEqual(len(ticket.token_hash), 64)
        with self.assertRaises(ContractDocumentTicketError):
            service.serve(token, actor_id=32)

        response = service.serve(token, actor_id=31, request_id="req-2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        response.file_to_stream.close()
        with self.assertRaises(ContractDocumentTicketError):
            service.serve(token, actor_id=31)

        self.assertEqual(HrContractDownloadTicket.objects.count(), 1)
        with self.assertRaises(ValidationError):
            HrContractDownloadTicket.objects.filter(pk=ticket.pk).update(
                created_by=32
            )
        self.assertEqual(
            set(HrContractAuditEvent.objects.values_list("action", flat=True)),
            {"document.ticket_generated", "document.download"},
        )

    def test_local_reference_binds_exact_document_to_signed_version(self):
        version = HrContractVersion.objects.create(
            tenant_id=7,
            agreement=self.agreement,
            version_no=1,
            effective_from=date(2026, 9, 1),
            signed_document_ref=f"hr07-document:{self.document.id}",
            content_snapshot_json={"title": "教师聘用合同"},
            content_hash="a" * 64,
            status=HrContractVersion.Status.SIGNED,
        )
        bind_signed_document_reference(
            tenant_id=7,
            agreement_id=self.agreement.id,
            version=version,
            signed_document_ref=version.signed_document_ref,
            actor_id=31,
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.version_id, version.id)
        self.assertEqual(
            self.document.signature_status,
            HrAgreementDocument.SignatureStatus.SIGNED,
        )

    def test_document_evidence_and_audit_history_are_immutable(self):
        self.document.file_path = "hr_contracts_private/7/tampered.pdf"
        with self.assertRaises(ValidationError):
            self.document.save(update_fields=("file_path", "updated_at"))
        with self.assertRaises(ValidationError):
            HrAgreementDocument.objects.filter(pk=self.document.pk).update(
                sha256="b" * 64
            )
        event = HrContractAuditEvent.objects.create(
            tenant_id=7,
            action="document.test",
            object_type="CONTRACT_DOCUMENT",
            object_id=str(self.document.id),
        )
        event.purpose = "tampered"
        with self.assertRaises(ValidationError):
            event.save(update_fields=("purpose",))
        with self.assertRaises(ValidationError):
            HrContractAuditEvent.objects.filter(pk=event.pk).delete()
