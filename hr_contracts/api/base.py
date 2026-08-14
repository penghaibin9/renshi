"""HR07 canonical API request/response helpers."""

import json
import uuid

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone

from hr_staff.context import resolve_tenant_from_request

API_VERSION = "1.0"
SCHEMA_VERSION = "hr07.agreement.1"


def resolve_contract_tenant(request) -> int:
    """Resolve a concrete selected school and verify membership server-side."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("UNAUTHENTICATED")

    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED")
    try:
        tenant_id = int(tenant_id)
    except (TypeError, ValueError):
        raise PermissionDenied("TENANT_CONTEXT_REQUIRED")

    if not getattr(user, "is_superuser", False):
        from base.auth_backends import get_allowed_company_ids

        allowed = set(get_allowed_company_ids(user) or ())
        if tenant_id not in allowed:
            raise PermissionDenied("TENANT_CONTEXT_REQUIRED")
    return tenant_id


def _request_id(request) -> str:
    request_id = getattr(request, "hr07_request_id", None)
    if request_id is None:
        request_id = uuid.uuid4().hex
        request.hr07_request_id = request_id
    return request_id


def api_success(request, data, *, status=200):
    body = {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": timezone.now().isoformat(),
        "data": data,
    }
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "no-store"
    return response


def api_error(request, code: str, message: str, *, status=400, details=None):
    body = {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": timezone.now().isoformat(),
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "retryable": False,
        },
    }
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "no-store"
    return response


def json_body(request) -> dict:
    try:
        body = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("request body must be valid JSON")
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body
