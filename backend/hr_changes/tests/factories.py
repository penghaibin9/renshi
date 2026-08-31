"""HR06 测试工厂（S3 起复用）。"""

from datetime import date

from django.utils import timezone

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


def make_effective_case(tenant_id: int, action_code=ChangeActionCode.ORG_TRANSFER, **kw):
    """Build a legitimate sealed EFFECTIVE chain for tests.

    MySQL deliberately rejects direct EFFECTIVE fixtures.  Tests needing a
    completed historical case must carry the same frozen approval and trusted
    execution evidence as production.
    """
    import uuid

    from hr_changes.constants import CaseStatus
    from hr_changes.models import (
        HrChangeApprovalSnapshot,
        HrChangeEffectiveSnapshot,
        HrChangeTransition,
    )
    from hr_changes.providers.effect import TrustedEffectReceipt
    from hr_changes.services.effect_intent import effect_intent_hash

    kw.pop("status", None)
    case = make_case(
        tenant_id,
        action_code,
        status=CaseStatus.APPLYING,
        **kw,
    )
    approval = HrChangeApprovalSnapshot.objects.create(
        change_case_id=case,
        workflow_version=1,
        steps_json=[{"step_no": 1, "status": "APPROVED", "approved_by": 9001}],
    )
    approval_hash = effect_intent_hash(case, approval)
    HrChangeTransition.objects.create(
        change_case_id=case,
        tenant_id=tenant_id,
        from_status=CaseStatus.UNDER_APPROVAL,
        to_status=CaseStatus.APPROVED_WAITING_EFFECTIVE,
        action="approve",
        actor_id=9001,
        snapshot_hash=approval_hash,
    )
    next_version = case.version + 1
    idempotency_key = f"fixture-effective:{case.id}"
    source_ids = [f"staff:{case.staff_master_id_id}:v{case.staff_master_id.version}"]
    target_ids = [f"fixture-authority:{uuid.uuid4()}"]
    receipt = TrustedEffectReceipt.issue(
        provider_code="HR06_CANONICAL_HR02_HR03_V1",
        tenant_id=tenant_id,
        case_id=case.id,
        case_version=next_version,
        staff_id=case.staff_master_id_id,
        action_code=case.action_id.code,
        effective_at=case.requested_effective_at,
        approval_snapshot_id=approval.id,
        approval_snapshot_hash=approval_hash,
        idempotency_key=idempotency_key,
        source_fact_ids=source_ids,
        target_fact_ids=target_ids,
        position_changes={},
        followup=[],
    )
    HrChangeEffectiveSnapshot.objects.create(
        change_case_id=case,
        applied_at=timezone.now(),
        effective_at=case.requested_effective_at,
        before_json={"fixture": "before"},
        after_json={"fixture": "after"},
        source_fact_ids_json=source_ids,
        target_fact_ids_json=target_ids,
        position_changes_json={},
        checksum="fixture-trusted-effect",
        case_version=next_version,
        approval_snapshot_id=approval.id,
        approval_snapshot_hash=approval_hash,
        provider_code=receipt.provider_code,
        provider_receipt_json=receipt.payload(),
        provider_receipt_hash=receipt.content_hash,
        execution_idempotency_key=idempotency_key,
    )
    case.approval_instance_id = str(approval.id)
    case.status = CaseStatus.EFFECTIVE
    case.version = next_version
    case.applied_at = timezone.now()
    case.save(
        update_fields=[
            "approval_instance_id",
            "status",
            "version",
            "applied_at",
            "updated_at",
        ]
    )
    return case
