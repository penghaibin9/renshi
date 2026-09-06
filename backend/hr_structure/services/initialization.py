"""Single-school initial structure command using the existing HR02 services.

The school row serializes initial commands. A unique durable receipt makes
retries safe; all versions, outbox events and the actor audit share one MySQL
transaction. Existing structures are never reset or silently adopted.
"""

import hashlib
import json

from auditlog.models import LogEntry
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from base.auth_backends import get_assigned_company_ids
from base.models import Company
from horilla.horilla_middlewares import get_selected_company
from hr_structure.initialization_forms import InitialStructureForm
from hr_structure.models import (
    HrOrganization, HrPosition, HrPostCatalog, HrSchoolStructureInitialization,
)
from hr_structure.scope import Hr02Scope
from hr_structure.services.organization_change import OrganizationChangeService
from hr_structure.services.position import PositionService
from hr_structure.services.post_catalog import PostCatalogService

SETUP_PERMISSIONS = (
    "hr.structure.organization.view", "hr.structure.organization.create",
    "hr.structure.post_catalog.view", "hr.structure.post_catalog.manage",
    "hr.structure.position.view", "hr.structure.position.manage",
)


class StructureSetupConflict(Exception):
    """A safe, actionable conflict; never include database diagnostics."""


def can_initialize(actor, tenant_id):
    return bool(
        actor and actor.is_authenticated and actor.is_active
        and str(get_selected_company()) == str(tenant_id)
        and tenant_id in get_assigned_company_ids(actor)
        and all(actor.has_perm(code) for code in SETUP_PERMISSIONS)
    )


def _hash_request(cleaned, school_name, effective_date):
    values = {**cleaned, "planned_fte": format(cleaned["planned_fte"], ".2f"),
              "school_name": school_name, "effective_date": effective_date.isoformat()}
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def initialization_for(tenant_id):
    return HrSchoolStructureInitialization.objects.filter(
        tenant_id=tenant_id, root_version__tenant_id=tenant_id, department_version__tenant_id=tenant_id,
        catalog_version__tenant_id=tenant_id, position__tenant_id=tenant_id,
    ).select_related(
        "root_version", "root_version__organization_id", "department_version",
        "department_version__organization_id", "catalog_version", "catalog_version__catalog_id",
        "position",
    ).first()


@transaction.atomic
def initialize_structure(*, tenant_id, actor, values, expected_school_name, effective_date):
    if not can_initialize(actor, tenant_id):
        raise PermissionDenied("请由本校获得组织、岗位目录及岗位管理授权的人员确认。")
    school = Company.objects.select_for_update().get(pk=tenant_id)
    form = InitialStructureForm(values)
    if not form.is_valid():
        raise ValidationError(form.errors.as_json())
    cleaned = form.cleaned_data
    request_hash = _hash_request(cleaned, expected_school_name, effective_date)
    receipt = initialization_for(tenant_id)
    if receipt:
        if receipt.request_hash != request_hash:
            raise StructureSetupConflict("本校已完成首次建立，请到组织与岗位工作区办理后续调整。")
        return receipt, False
    if effective_date != timezone.localdate() or school.company != expected_school_name:
        raise StructureSetupConflict("学校资料或办理日期已变化，请刷新页面后核对。")
    if not all(str(getattr(school, field) or "").strip()
               for field in ("company", "address", "country", "state", "city", "zip")):
        raise StructureSetupConflict("请先在学校管理中心保存完整的学校资料。")
    for model in (HrOrganization, HrPostCatalog, HrPosition):
        if model.objects.filter(tenant_id=tenant_id).exists():
            raise StructureSetupConflict("本校已有组织或岗位数据，本入口不会覆盖；请进入原工作区核验。")

    scope = Hr02Scope("SCHOOL", tenant_id)
    actor_id = str(actor.pk)
    organizations = OrganizationChangeService(scope, actor=actor_id)
    root = organizations.create_organization(
        stable_code=cleaned["root_code"], name=school.company, org_type="SCHOOL",
        dimension="ADMIN", validity_from=effective_date,
    )
    department = organizations.create_organization(
        stable_code=cleaned["department_code"], name=cleaned["department_name"],
        org_type=cleaned["department_type"], dimension="ADMIN", parent_id=root.pk,
        validity_from=effective_date,
    )
    catalog = PostCatalogService(scope, actor=actor_id).create_catalog(
        stable_code=cleaned["catalog_code"], name=cleaned["catalog_name"],
        category=cleaned["category"], validity_from=effective_date,
        standard_fte=cleaned["planned_fte"],
    )
    catalog_version = catalog.versions.get(tenant_id=tenant_id, version_no=1)
    position = PositionService(scope, actor=actor_id).create_position(
        position_code=cleaned["position_code"], organization_id=department.pk,
        post_catalog_version_id=catalog_version.pk, planned_fte=cleaned["planned_fte"],
        max_incumbents=1, allow_multiple_incumbents=False, validity_from=effective_date,
    )
    receipt = HrSchoolStructureInitialization.objects.create(
        tenant_id=tenant_id, request_hash=request_hash, created_by=actor_id,
        root_version=root.versions.get(tenant_id=tenant_id, version_no=1),
        department_version=department.versions.get(tenant_id=tenant_id, version_no=1),
        catalog_version=catalog_version, position=position,
    )
    LogEntry.objects.log_create(
        receipt, action=LogEntry.Action.CREATE, actor=actor,
        changes={"initial_structure": [None, str(receipt.pk)]},
        additional_data={"tenant_id": tenant_id, "source": "hr02_initial_structure",
                         "root_id": root.pk, "department_id": department.pk,
                         "catalog_version_id": catalog_version.pk, "position_id": position.pk},
    )
    return receipt, True
