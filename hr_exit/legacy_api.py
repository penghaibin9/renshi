"""Read-only legacy reconciliation API for HR16 cutover."""

from django.http import JsonResponse
from django.utils import timezone

from .api import HrExitAccessError, _error, resolve_request_tenant
from .services.legacy_reconciliation_service import LegacyExitReconciliationService


def legacy_reconciliation(request):
    """Return a tenant-scoped dual-read report without promoting legacy facts."""
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrExitAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    raw_limit = request.GET.get("limit", "200")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return _error("INVALID_LIMIT", "limit 必须是整数", status=400)

    data = LegacyExitReconciliationService(tenant_id).snapshot(limit=limit)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr16.legacy-reconciliation.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response
