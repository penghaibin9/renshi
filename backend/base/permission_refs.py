"""Exact permission reference helpers for RBAC mutation UIs.

Django stores permission uniqueness by content type + codename.  Using a bare
codename in an administrative POST can therefore grant/remove the same-named
permission from another app/model.  The UI contract here uses Django's familiar
``app_label.codename`` permission string and rejects ambiguous legacy bare
codenames rather than widening access.
"""
from __future__ import annotations

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError


def permission_ref(permission: Permission) -> str:
    return f"{permission.content_type.app_label}.{permission.codename}"


def permission_refs(queryset) -> list[str]:
    return sorted(
        f"{app_label}.{codename}"
        for app_label, codename in queryset.values_list(
            "content_type__app_label", "codename"
        )
    )


def resolve_permission_refs(values) -> list[Permission]:
    """Resolve exact app-qualified refs; legacy bare refs are accepted only if unique."""
    resolved_ids: set[int] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if "." in value:
            app_label, codename = value.split(".", 1)
            matches = list(
                Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename
                ).only("id")
            )
        else:
            matches = list(Permission.objects.filter(codename=value).only("id"))
        if len(matches) != 1:
            reason = "not found" if not matches else "ambiguous"
            raise ValidationError(f"Permission reference {value!r} is {reason}.")
        resolved_ids.add(matches[0].id)
    return list(
        Permission.objects.filter(id__in=resolved_ids).select_related("content_type")
    )
