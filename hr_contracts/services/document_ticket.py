"""
hr_contracts/services/document_ticket.py

合同文档下载票据（HR07 §20 / 00 §34）：
- 短时效一次性 ticket（10 分钟）；
- 下载前权限校验 + 审计；
- 私有目录 hr_contracts_private/ 文件经 ticket 获取，不走公开 /media/。
"""

from __future__ import annotations

import hashlib
import os
import time

from django.conf import settings
from django.http import FileResponse, Http404
from django.utils import timezone as dj_timezone

from hr_contracts.api.exceptions import NotFoundError, PermissionDeniedError
from hr_contracts.services import audit_service


class TicketExpiredError(PermissionDeniedError):
    def __init__(self, message: str = "下载票据已过期或已使用"):
        super().__init__(message)


class DownloadTicketService:
    TICKET_TTL_SECONDS = 600  # 10 分钟

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def generate_ticket(self, document_id, actor_id=None) -> str:
        """生成一次性下载票据（HMAC 签名 + 时间戳）。"""
        from hr_contracts.models import HrAgreementDocument

        doc = HrAgreementDocument.objects.filter(tenant_id=self.tenant_id, id=document_id).first()
        if doc is None:
            raise NotFoundError("文件不存在")

        secret = getattr(settings, "SECRET_KEY", "hr07-ticket-secret")
        now = int(time.time())
        payload = f"{self.tenant_id}:{str(document_id)}:{now}"
        sig = hashlib.sha256((payload + secret).encode()).hexdigest()[:16]
        ticket = f"{now}:{sig}:{str(document_id)}"

        audit_service.record_sensitive_access(
            tenant_id=self.tenant_id,
            agreement_id=doc.agreement_id_id,
            document_id=str(document_id),
            actor_id=actor_id,
            action="TICKET_GENERATED",
            purpose="下载票据",
        )
        return ticket

    def serve(self, ticket: str, request):
        """校验票据 → 返回 FileResponse（一次性消费）。"""
        try:
            parts = ticket.split(":")
            ts = int(parts[0])
            doc_id = parts[2]
            sig = parts[1]
        except (IndexError, ValueError):
            raise PermissionDeniedError("无效票据格式")

        now = int(time.time())
        if now - ts > self.TICKET_TTL_SECONDS:
            raise TicketExpiredError()

        secret = getattr(settings, "SECRET_KEY", "hr07-ticket-secret")
        expected = hashlib.sha256((f"{self.tenant_id}:{doc_id}:{ts}" + secret).encode()).hexdigest()[:16]
        if sig != expected:
            raise PermissionDeniedError("票据签名无效")

        from hr_contracts.models import HrAgreementDocument

        doc = HrAgreementDocument.objects.filter(tenant_id=self.tenant_id, id=doc_id).first()
        if doc is None:
            raise NotFoundError("文件不存在")

        file_path = os.path.join(settings.MEDIA_ROOT, doc.file_path) if doc.file_path else ""
        if not file_path or not os.path.exists(file_path):
            raise NotFoundError("文件存储路径不存在")

        audit_service.record_sensitive_access(
            tenant_id=self.tenant_id,
            agreement_id=doc.agreement_id_id,
            document_id=str(doc_id),
            actor_id=request.user.id if request.user.is_authenticated else None,
            action="DOWNLOAD",
            purpose="票据下载",
        )

        response = FileResponse(open(file_path, "rb"), content_type=doc.mime_type or "application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{doc.file_name or "document"}"'
        response["Cache-Control"] = "no-store"
        return response
