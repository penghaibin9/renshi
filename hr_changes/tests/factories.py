"""HR06 测试工厂（S3 起复用）。"""

from datetime import date

from hr_staff.tests.factories import make_org, make_person, make_staff
from hr_structure.models import (
    HrPostCatalog,
    HrPostCatalogVersion,
    HrPosition,
)

from hr_changes.constants import ChangeActionCode
from hr_changes.models import HrChangeAction, HrChangeReason, HrPersonnelChangeCase


def make_action(tenant_id: int, code=ChangeActionCode.ORG_TRANSFER, **kw) -> HrChangeAction:
    defaults = {"name": code, "is_temporary": code in ("TEMPORARY_SECONDMENT", "TEMPORARY_ATTACHMENT")}
    defaults.update(kw)
    action, _ = HrChangeAction.objects.get_or_create(
        tenant_id=tenant_id, code=code, defaults=defaults
    )
    return action


def make_reason(tenant_id: int, action_code, code="WORK_NEED", **kw) -> HrChangeReason:
    defaults = {"name": "工作需要"}
    defaults.update(kw)
    reason, _ = HrChangeReason.objects.get_or_create(
        tenant_id=tenant_id, action_code=action_code, code=code, defaults=defaults
    )
    return reason


def make_catalog_version(tenant_id: int, name="教师岗", validity_from=None) -> HrPostCatalogVersion:
    catalog = HrPostCatalog.objects.create(tenant_id=tenant_id, stable_code=f"PC-{name}-{tenant_id}")
    return HrPostCatalogVersion.objects.create(
        catalog_id=catalog,
        tenant_id=tenant_id,
        name=name,
        category="PROFESSIONAL_TECHNICAL",
        validity_from=validity_from or date(2020, 1, 1),
    )


def make_position(tenant_id: int, org, code: str, max_incumbents=1, validity_from=None) -> HrPosition:
    version = make_catalog_version(tenant_id, name=f"目录-{code}")
    return HrPosition.objects.create(
        tenant_id=tenant_id,
        position_code=code,
        organization_id=org,
        post_catalog_version_id=version,
        planned_fte=1.00,
        max_incumbents=max_incumbents,
        validity_from=validity_from or date(2020, 1, 1),
        lifecycle_status="ACTIVE",
    )


def make_case(
    tenant_id: int,
    action_code=ChangeActionCode.ORG_TRANSFER,
    *,
    case_no=None,
    target_org=None,
    target_position=None,
    source_org=None,
    source_position=None,
    requested_effective_at=None,
    status="DRAFT",
    with_relationship=True,
) -> HrPersonnelChangeCase:
    import uuid as _uuid

    action = make_action(tenant_id, action_code)
    reason = make_reason(tenant_id, action_code)
    final_case_no = case_no or f"HRCHG-2026-{abs(hash(_uuid.uuid4())) % 1000000:06d}"
    staff = make_staff(tenant_id, make_person(tenant_id, "张某某"), f"T-S3-{tenant_id}-{abs(hash((action_code, final_case_no))) % 1000000:06d}")
    if with_relationship:
        from hr_staff.services.employment_service import EmploymentService

        EmploymentService(tenant_id).start_relationship(
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
    return HrPersonnelChangeCase.objects.create(
        tenant_id=tenant_id,
        case_no=final_case_no,
        staff_master_id=staff,
        action_id=action,
        reason_id=reason,
        requested_effective_at=requested_effective_at or date(2026, 9, 1),
        source_org_id=source_org,
        target_org_id=target_org,
        source_position_id=source_position,
        target_position_id=target_position,
        status=status,
    )
