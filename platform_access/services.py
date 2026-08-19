import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from base.models import Company
from platform_access.models import PlatformTenantElevation

SESSION_KEY = "platform_tenant_elevation_id"
DEFAULT_DURATION_MINUTES = 30
MIN_DURATION_MINUTES = 5
MIN_REASON_LENGTH = 12


def _platform_actor(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    )


def _client_ip(request):
    return request.META.get("REMOTE_ADDR") or None


def _request_id(request):
    return (request.headers.get("X-Request-ID") or "")[:64]


def _user_agent_hash(request):
    value = request.headers.get("User-Agent") or ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _normalize_company_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def clear_elevation_session(request):
    if hasattr(request, "session"):
        request.session.pop(SESSION_KEY, None)
        request.session.modified = True
    request.platform_tenant_elevation = None
    request.platform_tenant_elevation_active = False


def grant_tenant_elevation(
    request,
    *,
    company_id,
    reason,
    duration_minutes=DEFAULT_DURATION_MINUTES,
    reference="",
):
    user = getattr(request, "user", None)
    if not _platform_actor(user):
        raise PermissionDenied("Platform superuser is required.")

    reason = " ".join(str(reason or "").split())
    if len(reason) < MIN_REASON_LENGTH:
        raise ValidationError(
            f"Elevation reason must be at least {MIN_REASON_LENGTH} characters."
        )

    try:
        duration_minutes = int(duration_minutes)
    except (TypeError, ValueError) as exc:
        raise ValidationError("duration_minutes must be an integer.") from exc

    max_minutes = int(
        getattr(settings, "PLATFORM_TENANT_ELEVATION_MAX_MINUTES", 60)
    )
    if not MIN_DURATION_MINUTES <= duration_minutes <= max_minutes:
        raise ValidationError(
            f"duration_minutes must be between {MIN_DURATION_MINUTES} and {max_minutes}."
        )

    company = Company.objects.filter(pk=_normalize_company_id(company_id)).first()
    if company is None:
        raise ValidationError("Target company does not exist.")

    now = timezone.now()
    expires_at = now + timedelta(minutes=duration_minutes)
    with transaction.atomic():
        active = PlatformTenantElevation.objects.select_for_update().filter(
            actor=user,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        active.update(
            revoked_at=now,
            revoked_by=user,
            revoked_reason="superseded by a new tenant elevation",
        )
        elevation = PlatformTenantElevation.objects.create(
            actor=user,
            company=company,
            reason=reason,
            reference=str(reference or "")[:120],
            granted_at=now,
            expires_at=expires_at,
            source_ip=_client_ip(request),
            request_id=_request_id(request),
            user_agent_hash=_user_agent_hash(request),
        )

    request.session[SESSION_KEY] = elevation.pk
    request.session.modified = True
    request.platform_tenant_elevation = elevation
    request.platform_tenant_elevation_active = True
    return elevation


def get_active_tenant_elevation(request, *, expected_company_id=None):
    user = getattr(request, "user", None)
    if not _platform_actor(user) or not hasattr(request, "session"):
        return None

    elevation_id = request.session.get(SESSION_KEY)
    if not elevation_id:
        return None

    elevation = (
        PlatformTenantElevation.objects.select_related("company", "actor")
        .filter(pk=elevation_id, actor=user)
        .first()
    )
    now = timezone.now()
    expected = _normalize_company_id(expected_company_id)
    if (
        elevation is None
        or elevation.revoked_at is not None
        or elevation.granted_at > now
        or elevation.expires_at <= now
        or (
            expected_company_id is not None
            and _normalize_company_id(elevation.company_id) != expected
        )
    ):
        clear_elevation_session(request)
        return None

    request.platform_tenant_elevation = elevation
    request.platform_tenant_elevation_active = True
    return elevation


def revoke_tenant_elevation(request, *, reason="operator revoked elevation"):
    user = getattr(request, "user", None)
    if not _platform_actor(user):
        raise PermissionDenied("Platform superuser is required.")

    elevation_id = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    if not elevation_id:
        clear_elevation_session(request)
        return None

    now = timezone.now()
    with transaction.atomic():
        elevation = (
            PlatformTenantElevation.objects.select_for_update()
            .filter(pk=elevation_id, actor=user)
            .first()
        )
        if elevation and elevation.revoked_at is None:
            elevation.revoked_at = now
            elevation.revoked_by = user
            elevation.revoked_reason = str(reason or "operator revoked elevation")[:255]
            elevation.save(
                update_fields=("revoked_at", "revoked_by", "revoked_reason")
            )

    clear_elevation_session(request)
    return elevation
