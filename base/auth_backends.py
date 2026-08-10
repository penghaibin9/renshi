"""Company-scoped permission helpers with fail-closed tenant semantics."""

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission

from horilla.horilla_middlewares import _thread_locals, get_selected_company


class CompanyScopedBackend(ModelBackend):
    """ModelBackend whose group grants are resolved inside the current school."""

    def _get_group_permissions(self, user_obj):
        if not getattr(settings, "COMPANY_SCOPED_PERMISSIONS", False):
            return super()._get_group_permissions(user_obj)

        selected = get_selected_company()
        # H0/A0 fail closed: session-less/API/job code does not inherit the
        # user's home school or the union of all school roles by accident.
        if selected is None:
            return Permission.objects.none()

        assignments = user_obj.company_group_assignments.all()
        if selected != "all":
            assignments = assignments.filter(company_id=selected)
        return Permission.objects.filter(
            group__company_assignments__in=assignments
        ).distinct()

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


def get_write_company_id(user):
    assigned = get_assigned_company_ids(user)
    pool = assigned or get_allowed_company_ids(user)
    if not pool:
        return None
    try:
        work_company_id = user.employee_get.employee_work_info.company_id_id
        if work_company_id in pool:
            return work_company_id
    except Exception:
        pass
    return sorted(pool)[0]


def resolve_company_id_for_new_record(request=None):
    """Resolve a concrete write tenant; returns None rather than guessing."""
    request = request or getattr(_thread_locals, "request", None)
    company = get_selected_company()
    if company and company != "all":
        try:
            return int(company)
        except (TypeError, ValueError):
            return company
    if not request or not getattr(request, "user", None):
        return None
    if not request.user.is_authenticated or request.user.is_superuser:
        return None
    if company_scoped_active() and company == "all":
        return get_write_company_id(request.user)
    return None


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
    try:
        return int(company_id) if company_id is not None else None
    except (TypeError, ValueError):
        return company_id


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
    if include_direct:
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
