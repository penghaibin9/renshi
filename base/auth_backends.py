"""Company-scoped authentication backend for the HR takeover."""

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission

from horilla.horilla_middlewares import _thread_locals, get_selected_company
from horilla.hr_permissions import (
    is_semantic_hr_permission,
    permission_aliases,
    semantic_codes_for_codename,
)


class CompanyScopedBackend(ModelBackend):
    """
    Resolve permissions inside the current school and understand semantic HR
    permission codes.

    Important differences from Django's default ModelBackend:
    - group grants are tenant scoped;
    - direct user permissions are disabled when tenant-scoped RBAC is active,
      because they are global and would bypass the selected school;
    - no cross-tenant permission cache is kept on the user object;
    - dotted business codenames (``hr.staff.view``) are resolved as codenames,
      not misread as Django app labels.
    """

    @staticmethod
    def _scoped_mode():
        return bool(getattr(settings, "COMPANY_SCOPED_PERMISSIONS", False))

    def _get_user_permissions(self, user_obj):
        if self._scoped_mode():
            return Permission.objects.none()
        return super()._get_user_permissions(user_obj)

    def _get_group_permissions(self, user_obj):
        if not self._scoped_mode():
            return super()._get_group_permissions(user_obj)

        selected = get_selected_company()
        if selected is None:
            return Permission.objects.none()

        assignments = user_obj.company_group_assignments.all()
        if selected != "all":
            assignments = assignments.filter(company_id=selected)
        return Permission.objects.filter(
            group__company_assignments__in=assignments
        ).distinct()

    def _effective_permission_objects(self, user_obj):
        if not getattr(user_obj, "is_active", False) or getattr(
            user_obj, "is_anonymous", True
        ):
            return Permission.objects.none()

        if getattr(user_obj, "is_superuser", False):
            return Permission.objects.all()

        user_ids = self._get_user_permissions(user_obj).values_list("pk", flat=True)
        group_ids = self._get_group_permissions(user_obj).values_list("pk", flat=True)
        return Permission.objects.filter(
            pk__in=user_ids.union(group_ids)
        ).select_related("content_type")

    @staticmethod
    def _render_permission_strings(permission_objects):
        rendered = set()
        for permission in permission_objects:
            rendered.add(f"{permission.content_type.app_label}.{permission.codename}")
            rendered.update(semantic_codes_for_codename(permission.codename))
        return rendered

    def get_user_permissions(self, user_obj, obj=None):
        if obj is not None:
            return set()
        permissions = self._get_user_permissions(user_obj).select_related(
            "content_type"
        )
        return self._render_permission_strings(permissions)

    def get_group_permissions(self, user_obj, obj=None):
        if obj is not None:
            return set()
        permissions = self._get_group_permissions(user_obj).select_related(
            "content_type"
        )
        return self._render_permission_strings(permissions)

    def get_all_permissions(self, user_obj, obj=None):
        if obj is not None:
            return set()
        return self._render_permission_strings(
            self._effective_permission_objects(user_obj)
        )

    def has_perm(self, user_obj, perm, obj=None):
        if not getattr(user_obj, "is_active", False):
            return False
        if getattr(user_obj, "is_superuser", False):
            return True
        if obj is not None:
            return False

        permissions = self.get_all_permissions(user_obj)
        if is_semantic_hr_permission(perm):
            return bool(permission_aliases(perm) & permissions)
        return perm in permissions

    @staticmethod
    def _resolve_company_id(user_obj):
        """Compatibility helper: never invent a tenant when context is absent."""
        company = get_selected_company()
        if company in (None, "all"):
            return None
        return company


def company_scoped_active():
    return bool(getattr(settings, "COMPANY_SCOPED_PERMISSIONS", False))


def get_assigned_company_ids(user):
    from base.models import CompanyGroupAssignment

    return set(
        CompanyGroupAssignment.objects.filter(user=user).values_list(
            "company_id", flat=True
        )
    )


def get_allowed_company_ids(user):
    ids = get_assigned_company_ids(user)
    try:
        work_company_id = user.employee_get.employee_work_info.company_id_id
        if work_company_id:
            ids.add(work_company_id)
    except Exception:
        pass
    return ids


def _coerce_company_id(company_id):
    try:
        return int(company_id)
    except (TypeError, ValueError):
        return company_id


def get_write_company_id(user):
    """
    Return the explicitly selected, authorized concrete tenant for a write.

    Read-only ``all`` scope may aggregate data across the user's assigned
    companies, but writes must never guess a tenant from work-info or from the
    first assignment. Missing/``all``/unauthorized context therefore returns
    ``None`` and the caller must require an explicit school selection.
    """
    selected = get_selected_company()
    if selected in (None, "", "all"):
        return None

    normalized = _coerce_company_id(selected)
    return normalized if normalized in get_allowed_company_ids(user) else None


def resolve_company_id_for_new_record(request=None):
    """
    Resolve one concrete write tenant without inventing one.

    Background jobs/providers are allowed to write under an explicit
    ``tenant_context(company_id)`` even when there is no HTTP request. Web
    requests additionally verify that the selected school is within the
    authenticated user's allowed tenant set.
    """
    request = request or getattr(_thread_locals, "request", None)
    company = get_selected_company()
    if company in (None, "", "all"):
        return None

    normalized = _coerce_company_id(company)
    if request is None:
        return normalized

    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return normalized
    if company_scoped_active() and normalized not in get_allowed_company_ids(user):
        return None
    return normalized


def stamp_company_on_create(instance, attr="company_id"):
    if getattr(instance, "pk", None):
        return False
    fk_id_attr = f"{attr}_id"
    if getattr(instance, fk_id_attr, None):
        return False
    company_id = resolve_company_id_for_new_record()
    if not company_id:
        return False
    from base.models import Company

    company = Company.find(company_id)
    if not company:
        return False
    setattr(instance, attr, company)
    return True


def _normalize_company_id(company_id=None):
    if company_id is None:
        company_id = get_selected_company()
    if company_id in ("", "all"):
        return None
    return _coerce_company_id(company_id) if company_id is not None else None


def get_user_groups_for_company(user, company_id=None):
    from django.contrib.auth.models import Group

    if not user:
        return Group.objects.none()
    if not company_scoped_active():
        return user.groups.all()

    explicit = company_id if company_id is not None else get_selected_company()
    if explicit is None:
        return Group.objects.none()

    assignments = user.company_group_assignments.all()
    normalized = _normalize_company_id(explicit)
    if normalized is not None:
        assignments = assignments.filter(company_id=normalized)
    return Group.objects.filter(
        id__in=assignments.values_list("group_id", flat=True)
    ).distinct()


def get_effective_permission_codenames(user, company_id=None, include_direct=True):
    if not user:
        return []

    codenames = set()
    if include_direct and not company_scoped_active():
        codenames.update(user.user_permissions.values_list("codename", flat=True))

    if not company_scoped_active():
        codenames.update(
            Permission.objects.filter(group__user=user).values_list(
                "codename", flat=True
            )
        )
        return sorted(codenames)

    explicit = company_id if company_id is not None else get_selected_company()
    if explicit is None:
        return sorted(codenames)

    assignments = user.company_group_assignments.all()
    normalized = _normalize_company_id(explicit)
    if normalized is not None:
        assignments = assignments.filter(company_id=normalized)
    codenames.update(
        Permission.objects.filter(
            group__company_assignments__in=assignments
        ).values_list("codename", flat=True)
    )
    return sorted(codenames)


def get_permission_company_label(company_id=None):
    from base.models import Company

    explicit = company_id if company_id is not None else get_selected_company()
    if explicit is None:
        return None
    if explicit == "all":
        return "All my companies"
    normalized = _normalize_company_id(explicit)
    company = Company.objects.filter(id=normalized).first()
    return company.company if company else None
