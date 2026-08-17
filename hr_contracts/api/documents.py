"""
hr_contracts/api/documents.py

文档下载票据 API（HR07 §20 / 00 §34）。
"""

from __future__ import annotations

from django.views.decorators.http import require_GET, require_POST

from hr_contracts.api.base import handle_hr07_error, make_hr07_context, ok
from hr_contracts.permissions import require_hr_contract_permission
from hr_contracts.services.document_ticket import DownloadTicketService


@require_POST
@require_hr_contract_permission("hr.contract.document.download")
def generate_ticket(request, document_id):
    try:
        ctx = make_hr07_context(request)
        ticket = DownloadTicketService(ctx.tenant_id).generate_ticket(
            document_id, actor_id=request.user.id if request.user.is_authenticated else None
        )
        return ok(request, {"ticket": ticket, "documentId": str(document_id)})
    except Exception as exc:
        return handle_hr07_error(request, exc)


@require_GET
@require_hr_contract_permission("hr.contract.document.download")
def download_via_ticket(request, ticket):
    try:
        ctx = make_hr07_context(request)
        return DownloadTicketService(ctx.tenant_id).serve(ticket, request)
    except Exception as exc:
        return handle_hr07_error(request, exc)
