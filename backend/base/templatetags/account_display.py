"""Read-only account display projection, never school management authority."""
from django import template
from django.core.exceptions import PermissionDenied
from django.http import Http404

register = template.Library()


@register.simple_tag(takes_context=True)
def account_display_preferences(context):
    """Embed only display formats from a proven current school in this document.

    Reuse the existing school/elevation resolver, but not its admin-only API.
    Anonymous, absent, combined or unauthorised scopes get non-school defaults.
    No school is guessed and no database or browser preference is written.
    """
    result = {"dateFormat": "MMM. D, YYYY", "timeFormat": "hh:mm A",
              "companyId": None, "source": "DEFAULT"}
    request = context.get("request")
    if not request or not getattr(request.user, "is_authenticated", False) or not request.user.is_active:
        return result
    from base.settings_center import DATE_FORMATS, TIME_FORMATS, _selected_company

    try:
        company = _selected_company(request)
    except (PermissionDenied, Http404):
        return result
    company.refresh_from_db(fields=["date_format", "time_format"])
    result.update(companyId=company.pk, source="SCHOOL")
    if company.date_format in DATE_FORMATS:
        result["dateFormat"] = company.date_format
    if company.time_format in TIME_FORMATS:
        result["timeFormat"] = company.time_format
    return result


@register.simple_tag(takes_context=True)
def account_self_navigation_only(context):
    """Compact only accounts whose current effective grants are SELF view alone.

    Multi-role users keep the existing module navigation; no alternate role
    registry or grant is created. Endpoints still make their own access checks.
    """
    request = context.get("request")
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_active or user.is_superuser:
        return False
    from horilla.hr_permissions import permission_aliases
    from hr_staff.account_contract import SELF_PERMISSION

    aliases = permission_aliases(SELF_PERMISSION)
    allowed = set(aliases) | {f"hr_self.{code}" for code in aliases}
    permissions = user.get_all_permissions()
    return bool(permissions & aliases) and permissions <= allowed
