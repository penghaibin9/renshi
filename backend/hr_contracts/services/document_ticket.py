"""Short-lived, durable, single-use download tickets for HR07 documents."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.http import FileResponse
from django.utils import timezone

from hr_contracts.services import audit_service
from hr_contracts.services.document_storage import open_contract_document


class ContractDocumentTicketError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class DownloadTicketService:
    TICKET_TTL_SECONDS = 600

    def __init__(self, tenant_id: int):
        self.tenant_id = int(tenant_id)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @transaction.atomic
    def generate_ticket(
        self, document_id, *, actor_id: int, purpose: str, request_id: str = ""
    ) -> tuple[str, object]:
        from hr_contracts.models import HrAgreementDocument, HrContractDownloadTicket

        purpose = str(purpose or "").strip()
        if not purpose:
            raise ContractDocumentTicketError(
                "CONTRACT_DOCUMENT_PURPOSE_REQUIRED", "请填写下载合同文档的用途"
            )
        document = (
            HrAgreementDocument.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=document_id)
            .first()
        )
        if document is None:
            raise ContractDocumentTicketError(
                "CONTRACT_DOCUMENT_NOT_FOUND", "合同文档不存在", status=404
            )

        token = secrets.token_urlsafe(32)
        ticket = HrContractDownloadTicket.objects.create(
            tenant_id=self.tenant_id,
            document=document,
            token_hash=self._hash(token),
            purpose=purpose[:300],
            expires_at=timezone.now() + timedelta(seconds=self.TICKET_TTL_SECONDS),
            created_by=actor_id,
            updated_by=actor_id,
        )
        audit_service.record_sensitive_access(
            tenant_id=self.tenant_id,
            agreement_id=document.agreement_id,
            document_id=str(document.id),
            actor_id=actor_id,
            action="TICKET_GENERATED",
            purpose=purpose,
            request_id=request_id,
        )
        return token, ticket

    @transaction.atomic
    def serve(self, token: str, *, actor_id: int, request_id: str = ""):
        from hr_contracts.models import HrContractDownloadTicket

        ticket = (
            HrContractDownloadTicket.objects.select_for_update()
            .select_related("document")
            .filter(
                tenant_id=self.tenant_id,
                token_hash=self._hash(str(token or "")),
                created_by=actor_id,
            )
            .first()
        )
        now = timezone.now()
        if ticket is None or ticket.consumed_at is not None or ticket.expires_at <= now:
            raise ContractDocumentTicketError(
                "CONTRACT_DOCUMENT_TICKET_INVALID",
                "下载凭证无效、已过期或已使用",
                status=403,
            )

        document = ticket.document
        stream = open_contract_document(
            document.file_path,
            tenant_id=self.tenant_id,
            agreement_id=document.agreement_id,
        )
        try:
            ticket.consumed_at = now
            ticket.updated_by = actor_id
            ticket.save(update_fields=("consumed_at", "updated_by", "updated_at"))
            audit_service.record_sensitive_access(
                tenant_id=self.tenant_id,
                agreement_id=document.agreement_id,
                document_id=str(document.id),
                actor_id=actor_id,
                action="DOWNLOAD",
                purpose=ticket.purpose,
                request_id=request_id,
            )
        except Exception:
            stream.close()
            raise

        response = FileResponse(
            stream,
            as_attachment=True,
            filename=document.file_name or f"contract-{document.id}.pdf",
            content_type=document.mime_type or "application/pdf",
        )
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response
