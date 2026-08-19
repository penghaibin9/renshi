import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from horilla.horilla_middlewares import set_selected_company
from platform_access.services import (
    get_active_tenant_elevation,
    grant_tenant_elevation,
    revoke_tenant_elevation,
)


def _payload(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Request body must be valid JSON.") from exc
    return request.POST


def _platform_user(request):
    user = getattr(request, "user", None)
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    )


def _forbidden():
    return JsonResponse({"detail": "Platform superuser is required."}, status=403)


@require_POST
def activate_tenant_elevation(request):
    if not _platform_user(request):
        return _forbidden()
    try:
        payload = _payload(request)
        elevation = grant_tenant_elevation(
            request,
            company_id=payload.get("company_id"),
            reason=payload.get("reason"),
            duration_minutes=payload.get("duration_minutes", 30),
            reference=payload.get("reference", ""),
        )
    except (ValidationError, PermissionDenied) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse({"detail": message}, status=400)

    request.session["selected_company"] = str(elevation.company_id)
    request.session.modified = True
    set_selected_company(elevation.company_id)
    return JsonResponse(
        {
            "active": True,
            "elevation_id": elevation.pk,
            "company_id": elevation.company_id,
            "expires_at": elevation.expires_at.isoformat(),
            "reference": elevation.reference,
        },
        status=201,
    )


@require_POST
def revoke_current_tenant_elevation(request):
    if not _platform_user(request):
        return _forbidden()
    try:
        payload = _payload(request)
        elevation = revoke_tenant_elevation(
            request,
            reason=payload.get("reason", "operator revoked elevation"),
        )
    except (ValidationError, PermissionDenied) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
        return JsonResponse({"detail": message}, status=400)

    request.session["selected_company"] = "all"
    request.session.modified = True
    set_selected_company("all")
    return JsonResponse(
        {
            "active": False,
            "revoked_elevation_id": elevation.pk if elevation else None,
        }
    )


@require_GET
def tenant_elevation_status(request):
    if not _platform_user(request):
        return _forbidden()
    elevation = get_active_tenant_elevation(request)
    if elevation is None:
        return JsonResponse({"active": False})
    return JsonResponse(
        {
            "active": True,
            "elevation_id": elevation.pk,
            "company_id": elevation.company_id,
            "expires_at": elevation.expires_at.isoformat(),
            "reference": elevation.reference,
        }
    )
