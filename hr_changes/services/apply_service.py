"""
hr_changes/services/apply_service.py —— 生效事务（S8，总册 §48/§50，HR06 P0）。

apply_change(case):
    lock(case)
    ensure APPROVED_WAITING_EFFECTIVE
    ensure due
    revalidate current facts（BLOCKER → APPLY_FAILED，不静默）
    rebase（HARD_CONFLICT → APPLY_FAILED）
    mark APPLYING
    ── nested savepoint: HR03 domain service 写事实 + HR02 PositionGate required commit
    ── 任一失败：回滚 domain savepoint，再把 case 标 APPLY_FAILED
    save effective snapshot（checksum 不可变）
    mark EFFECTIVE
    outbox（PersonnelChangeEffective + 下游 effects）

禁止：直接批量 UPDATE WorkInformation；岗位预占缺失/提交失败静默通过；
禁止捕获领域异常后仍保留已经部分写入的 HR03 事实。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_changes.constants import (
    CaseStatus,
    ChangeActionCode,
    DownstreamEffectStatus,
    FutureConflictResult,
)
from hr_changes.integrations.hr02 import PositionGate
from hr_changes.integrations.outbox import enqueue_outbox
from hr_changes.models import (
    HrChangeDownstreamEffect,
    HrChangeEffectiveSnapshot,
    HrPersonnelChangeCase,
    HrTemporaryAssignmentLink,
)
from hr_changes.providers.effect import (
    EffectProviderError,
    SUPPORTED_EFFECT_ACTIONS,
    build_default_effect_provider_registry,
)
from hr_changes.services.change_service import ChangeService, ChangeServiceError
from hr_changes.services.rebase_service import RebaseService
from hr_changes.services.state_machine import transition


class ApplyServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ApplyService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: Optional[int] = None,
        provider_registry=None,
    ):
        if not tenant_id:
            raise ApplyServiceError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.change_service = ChangeService(tenant_id, actor_user_id=actor_user_id)
        self.position_gate = PositionGate(tenant_id)
        self.provider_registry = (
            provider_registry or build_default_effect_provider_registry()
        )

    # ------------------------------------------------------------------
    @transaction.atomic
    def apply_case(
        self,
        case_id,
        *,
        effective_at: Optional[date] = None,
        as_of: Optional[date] = None,
        expected_version: Optional[int] = None,
        request_id: str = "",
    ) -> HrPersonnelChangeCase:
        case = (
            HrPersonnelChangeCase.objects.select_for_update()
            .select_related(
                "staff_master_id",
                "employment_relationship_id",
                "source_assignment_id__employment_relationship_id",
                "action_id",
            )
            .filter(tenant_id=self.tenant_id, id=case_id)
            .first()
        )
        if case is None:
            raise ApplyServiceError("CHANGE_NOT_FOUND", "异动案件不存在")
        idempotency_key = request_id.strip() or f"hr06-effect:{self.tenant_id}:{case.id}"
        if case.status == CaseStatus.EFFECTIVE:
            snapshot = getattr(case, "effective_snapshot", None)
            if (
                snapshot
                and snapshot.execution_idempotency_key == idempotency_key
                and snapshot.provider_code == "HR06_CANONICAL_HR02_HR03_V1"
                and len(snapshot.provider_receipt_hash or "") == 64
            ):
                return case
            raise ApplyServiceError(
                "IDEMPOTENCY_KEY_CONFLICT",
                "case is already effective under a different execution key",
            )
        if expected_version is not None and case.version != expected_version:
            raise ApplyServiceError("VERSION_CONFLICT", "case version changed")
        if case.status not in (
            CaseStatus.APPROVED_WAITING_EFFECTIVE,
            CaseStatus.APPLY_FAILED,
        ):
            raise ApplyServiceError("CHANGE_INVALID_STATE", "仅已批准待生效案件可执行生效")

        approved_effective_at = (
            case.approved_effective_at or case.requested_effective_at
        )
        eff = effective_at or approved_effective_at
        if eff != approved_effective_at:
            raise ApplyServiceError(
                "CHANGE_EFFECTIVE_DATE_INVALID",
                "生效日必须与冻结审批意图一致",
            )

        business_day = as_of or timezone.localdate()
        if type(business_day) is not date:
            raise ApplyServiceError("CHANGE_EFFECTIVE_DATE_INVALID", "as_of must be a date")
        if eff > business_day:
            raise ApplyServiceError(
                "CHANGE_EFFECTIVE_DATE_INVALID", "尚未到达生效日，不能提前生效"
            )

        # 1) 冻结审批链与 Authority 父链必须完整；provider 缺失明确失败。
        try:
            approval, approval_hash = self._trusted_approval(case)
            self._validate_parent_lineage(case)
            provider = self.provider_registry.require(case.action_id.code)
        except (ApplyServiceError, EffectProviderError) as exc:
            return self._mark_apply_failed(case, idempotency_key, exc.code)

        # 2) 生效前重新校验（BLOCKER 不静默）
        from hr_changes.services.impact_service import ImpactService

        blockers = ImpactService(self.tenant_id).check_blockers(case, as_of=eff)
        if blockers:
            self._mark_apply_failed(case, idempotency_key, blockers[0]["code"])
            return case

        # 3) Future 冲突/Rebase
        rebase = RebaseService(self.tenant_id).check(case, eff)
        if rebase == FutureConflictResult.HARD_CONFLICT:
            self._mark_apply_failed(
                case, idempotency_key, "CHANGE_FUTURE_EVENT_CONFLICT"
            )
            return case

        # 4) 标记 APPLYING
        transition_action = (
            "retry_apply" if case.status == CaseStatus.APPLY_FAILED else "apply"
        )
        case = self.change_service._apply_transition(
            case,
            transition_action,
            CaseStatus.APPLYING,
            comment="重试生效" if transition_action == "retry_apply" else "开始生效",
            request_id=idempotency_key,
        )

        # 5) provider 写入：必须放在 nested savepoint 中。
        # 这样 HR03 已写成功但 HR02 reservation commit 失败时，会先回滚领域写入，
        # 然后在外层事务里安全记录 APPLY_FAILED，而不是留下“半生效”事实。
        before = _capture_facts(self.tenant_id, case, eff)
        try:
            with transaction.atomic():
                receipt = provider.execute(
                    executor=self._apply_domain,
                    case=case,
                    effective_at=eff,
                    case_version=case.version + 1,
                    approval_snapshot_id=approval.id,
                    approval_snapshot_hash=approval_hash,
                    idempotency_key=idempotency_key,
                )
                receipt.verify(
                    tenant_id=self.tenant_id,
                    case_id=case.id,
                    case_version=case.version + 1,
                    staff_id=case.staff_master_id_id,
                    action_code=case.action_id.code,
                    effective_at=eff,
                    approval_snapshot_id=approval.id,
                    approval_snapshot_hash=approval_hash,
                    idempotency_key=idempotency_key,
                )
                after = _capture_facts(self.tenant_id, case, eff)
        except Exception as exc:
            code = getattr(exc, "code", "CHANGE_APPLY_DOMAIN_FAILED")
            case = self.change_service._apply_transition(
                case,
                "apply_failed",
                CaseStatus.APPLY_FAILED,
                comment=f"生效失败: {code}: {exc}",
                request_id=idempotency_key,
            )
            enqueue_outbox(
                tenant_id=self.tenant_id,
                event_type="PersonnelChangeApplyFailed",
                aggregate_type="PersonnelChangeCase",
                aggregate_id=str(case.id),
                correlation_id=idempotency_key,
                payload={
                    "caseNo": case.case_no,
                    "code": code,
                    "error": str(exc)[:500],
                },
            )
            return case

        # 6) 生效快照（不可变，绑定 provider + 审批回执）
        checksum = hashlib.sha256(
            json.dumps(
                {"before": before, "after": after, "case": str(case.id)},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        HrChangeEffectiveSnapshot.objects.create(
            change_case_id=case,
            applied_at=timezone.now(),
            effective_at=eff,
            before_json=before,
            after_json=after,
            source_fact_ids_json=receipt.source_fact_ids,
            target_fact_ids_json=receipt.target_fact_ids,
            position_changes_json=receipt.position_changes,
            checksum=checksum,
            case_version=case.version + 1,
            approval_snapshot_id=approval.id,
            approval_snapshot_hash=approval_hash,
            provider_code=receipt.provider_code,
            provider_receipt_json=receipt.payload(),
            provider_receipt_hash=receipt.content_hash,
            execution_idempotency_key=idempotency_key,
        )

        # 7) 只有可信快照写入成功后才标记 EFFECTIVE
        case = self.change_service._apply_transition(
            case,
            "apply_success",
            CaseStatus.EFFECTIVE,
            comment="已生效",
            request_id=idempotency_key,
            applied_at=timezone.now(),
        )

        # 8) Outbox + 下游效果记录
        enqueue_outbox(
            tenant_id=self.tenant_id,
            event_type="PersonnelChangeEffective",
            aggregate_type="PersonnelChangeCase",
            aggregate_id=str(case.id),
            correlation_id=idempotency_key,
            payload={
                "caseNo": case.case_no,
                "effectiveAt": eff.isoformat(),
                "checksum": checksum,
                "staffId": str(case.staff_master_id_id),
                "providerCode": receipt.provider_code,
                "providerReceiptHash": receipt.content_hash,
                "approvalSnapshotHash": approval_hash,
            },
        )
        self._record_downstream_effects(case, {"followup": receipt.followup})

        return case

    # ------------------------------------------------------------------
    def _trusted_approval(self, case):
        from hr_changes.models import HrChangeApprovalSnapshot

        approval = (
            HrChangeApprovalSnapshot.objects.select_for_update()
            .filter(
                id=case.approval_instance_id,
                change_case_id=case,
            )
            .first()
        )
        steps = list(approval.steps_json or []) if approval else []
        if not steps or any(
            step.get("status") != "APPROVED" or not step.get("approved_by")
            for step in steps
        ):
            raise ApplyServiceError(
                "CHANGE_APPROVAL_SNAPSHOT_MISMATCH",
                "frozen approval chain is missing or incomplete",
            )
        from hr_changes.models import HrChangeTransition
        from hr_changes.services.effect_intent import effect_intent_hash

        approval_hash = effect_intent_hash(case, approval)
        frozen = (
            HrChangeTransition.objects.filter(
                tenant_id=self.tenant_id,
                change_case_id=case,
                action="approve",
                to_status=CaseStatus.APPROVED_WAITING_EFFECTIVE,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if frozen is None or frozen.snapshot_hash != approval_hash:
            raise ApplyServiceError(
                "CHANGE_APPROVAL_SNAPSHOT_MISMATCH",
                "approved intent no longer matches its frozen transition",
            )
        return approval, approval_hash

    def _validate_parent_lineage(self, case):
        if int(case.staff_master_id.tenant_id) != int(self.tenant_id):
            raise ApplyServiceError(
                "CROSS_TENANT_REFERENCE", "staff and case tenant mismatch"
            )
        relationship = case.employment_relationship_id
        if relationship is not None and (
            int(relationship.tenant_id) != int(self.tenant_id)
            or str(relationship.staff_id_id) != str(case.staff_master_id_id)
        ):
            raise ApplyServiceError(
                "CROSS_TENANT_REFERENCE", "relationship parent lineage mismatch"
            )
        assignment = case.source_assignment_id
        if assignment is not None and (
            int(assignment.tenant_id) != int(self.tenant_id)
            or str(assignment.employment_relationship_id.staff_id_id)
            != str(case.staff_master_id_id)
        ):
            raise ApplyServiceError(
                "CROSS_TENANT_REFERENCE", "assignment parent lineage mismatch"
            )

    # ------------------------------------------------------------------
    def _record_downstream_effects(self, case, domain_result: dict):
        followup = domain_result.get("followup", [])
        for target_domain, effect_type in followup:
            HrChangeDownstreamEffect.objects.create(
                change_case_id=case,
                tenant_id=self.tenant_id,
                target_domain=target_domain,
                effect_type=effect_type,
                status=DownstreamEffectStatus.PENDING,
            )

    def _mark_apply_failed(self, case, request_id: str, code: str):
        if case.status == CaseStatus.APPLY_FAILED:
            return case
        case = self.change_service._apply_transition(
            case,
            "apply_failed",
            CaseStatus.APPLY_FAILED,
            comment=f"生效前校验阻断: {code}",
            request_id=request_id,
        )
        enqueue_outbox(
            tenant_id=self.tenant_id,
            event_type="PersonnelChangeApplyFailed",
            aggregate_type="PersonnelChangeCase",
            aggregate_id=str(case.id),
            payload={"caseNo": case.case_no, "code": code},
        )
        return case

    # ------------------------------------------------------------------
    # 领域写入（S8：只经 HR03 domain service）
    # ------------------------------------------------------------------
    def _apply_domain(self, case: HrPersonnelChangeCase, eff: date) -> dict:
        from hr_staff.services.assignment_service import (
            AssignmentPolicyViolation,
            AssignmentService,
        )
        from hr_staff.services.employment_service import EmploymentService
        from hr_staff.services.staff_master_service import StaffMasterService

        action = case.action_id.code
        if action not in SUPPORTED_EFFECT_ACTIONS:
            raise ApplyServiceError(
                "CHANGE_INVALID_ACTION",
                f"异动动作 {action} 未接入可信 Authority provider",
            )
        proposals = {p.field_code: p for p in case.proposals.all()}
        assignment_service = AssignmentService(
            self.tenant_id, audit_actor_user_id=self.actor_user_id
        )
        biz_type = _map_source_business_type(action)
        biz_id = case.case_no

        def _ref(field):
            p = proposals.get(field)
            return p.proposed_value_ref if p else None

        source_fact_ids = [str(case.id)]
        target_fact_ids = []

        target_org = _resolve_org(
            self.tenant_id,
            case.target_org_id_id or _ref("organization"),
        )
        target_pos = _resolve_position(
            self.tenant_id,
            case.target_position_id_id or _ref("position"),
        )
        target_catalog = _resolve_catalog(self.tenant_id, _ref("post_catalog"))
        if (
            action
            in (
                ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
                ChangeActionCode.ADD_SECONDARY_ASSIGNMENT,
            )
            and target_catalog is None
            and target_pos is not None
        ):
            target_catalog = target_pos.post_catalog_version_id
        reporting_staff = _resolve_staff(self.tenant_id, _ref("reporting_staff"))

        if action == ChangeActionCode.ORG_TRANSFER and target_org is None:
            raise ApplyServiceError("CHANGE_TARGET_ORG_INVALID", "组织调动缺少可信目标组织")
        if action == ChangeActionCode.POSITION_TRANSFER and target_pos is None:
            raise ApplyServiceError("CHANGE_TARGET_POSITION_INVALID", "岗位调动缺少可信目标岗位")
        if action in (
            ChangeActionCode.ORG_POSITION_TRANSFER,
            ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
            ChangeActionCode.ADD_SECONDARY_ASSIGNMENT,
        ) and (target_org is None or target_pos is None):
            raise ApplyServiceError(
                "CHANGE_INVALID_PAYLOAD", "该异动缺少可信目标组织或岗位"
            )
        if action == ChangeActionCode.MANAGER_CHANGE and reporting_staff is None:
            raise ApplyServiceError("STAFF_NOT_FOUND", "直属上级不存在或跨租户")
        if action in (
            ChangeActionCode.TEMPORARY_SECONDMENT,
            ChangeActionCode.TEMPORARY_ATTACHMENT,
        ) and target_org is None:
            raise ApplyServiceError("CHANGE_TARGET_ORG_INVALID", "临时异动缺少可信目标组织")

        if action in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.POSITION_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
            ChangeActionCode.PRIMARY_ASSIGNMENT_SWITCH,
        ):
            try:
                new_primary = assignment_service.switch_primary(
                    employment_relationship_id=(
                        case.employment_relationship_id
                        or _current_rel(self.tenant_id, case, eff)
                    ),
                    effective_from=eff,
                    organization_id=target_org,
                    position_id=target_pos,
                    post_catalog_id=target_catalog,
                    fte=_decimal_or_none(_ref("fte")) or 1,
                    reporting_staff_id=reporting_staff,
                    source_business_type=biz_type,
                    source_business_id=biz_id,
                )
                target_fact_ids.append(str(new_primary.id))
            except AssignmentPolicyViolation as exc:
                raise ApplyServiceError(
                    exc.code or "ASSIGNMENT_OVERLAP",
                    exc.args[0] if exc.args else "主岗切换失败",
                )

            # 只有真正涉及目标岗位的动作才要求 reservation；一旦需要，必须存在并提交成功。
            if self.position_gate.needs_position(action):
                try:
                    reservation = self.position_gate.require_commit_for_case(case)
                    target_fact_ids.append(f"position-reservation:{reservation.id}")
                except Exception as exc:
                    raise ApplyServiceError(
                        getattr(
                            exc,
                            "code",
                            "CHANGE_POSITION_RESERVATION_COMMIT_FAILED",
                        ),
                        str(exc) or "目标岗位预占提交失败",
                    ) from exc

        elif action == ChangeActionCode.ADD_SECONDARY_ASSIGNMENT:
            new_secondary = assignment_service.create_assignment(
                employment_relationship_id=_current_rel(self.tenant_id, case, eff),
                assignment_type="CONCURRENT",
                effective_from=eff,
                organization_id=target_org,
                position_id=target_pos,
                post_catalog_id=target_catalog,
                fte=_decimal_or_none(_ref("fte")) or 1,
                source_business_type=biz_type,
                source_business_id=biz_id,
            )
            target_fact_ids.append(str(new_secondary.id))
            try:
                reservation = self.position_gate.require_commit_for_case(case)
                target_fact_ids.append(f"position-reservation:{reservation.id}")
            except Exception as exc:
                raise ApplyServiceError(
                    getattr(
                        exc,
                        "code",
                        "CHANGE_POSITION_RESERVATION_COMMIT_FAILED",
                    ),
                    str(exc) or "目标岗位预占提交失败",
                ) from exc

        elif action == ChangeActionCode.END_SECONDARY_ASSIGNMENT:
            from hr_staff.constants import AssignmentType
            from hr_staff.services.effective_dated_query_service import (
                EffectiveDatedQueryService,
            )

            source_assignment = (
                EffectiveDatedQueryService(self.tenant_id)
                .assignments_as_of(case.staff_master_id_id, eff)
                .filter(
                    id=case.source_assignment_id_id,
                    assignment_type=AssignmentType.CONCURRENT,
                )
                .first()
            )
            if source_assignment is None:
                raise ApplyServiceError(
                    "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                    "未找到所选的生效中兼岗",
                )
            assignment_service.close_assignment(
                assignment_id=source_assignment.id,
                effective_to=eff,
                source_business_type=biz_type,
                source_business_id=biz_id,
            )
            target_fact_ids.append(str(source_assignment.id))

        elif action == ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE:
            if not (_ref("staff_category_code") or "").strip():
                raise ApplyServiceError(
                    "CHANGE_INVALID_PAYLOAD", "人员类别不能为空"
                )
            StaffMasterService().update_staff_category(
                tenant_id=self.tenant_id,
                staff_id=case.staff_master_id_id,
                staff_category_code=_ref("staff_category_code") or "",
                source_business_type=biz_type,
                source_business_id=biz_id,
                reason_code=case.reason_id.code,
            )
            case.staff_master_id.refresh_from_db()
            target_fact_ids.append(
                f"staff:{case.staff_master_id_id}:v{case.staff_master_id.version}"
            )

        elif action == ChangeActionCode.EMPLOYMENT_TYPE_CHANGE:
            rel = _current_rel(self.tenant_id, case, eff)
            if rel is None:
                raise ApplyServiceError("RELATIONSHIP_NOT_FOUND", "未找到聘用关系")
            if not (_ref("relationship_type") or "").strip():
                raise ApplyServiceError(
                    "CHANGE_INVALID_PAYLOAD", "聘用关系类型不能为空"
                )
            EmploymentService(
                self.tenant_id,
                audit_actor_user_id=self.actor_user_id,
            ).update_relationship_type(
                relationship_id=rel.id,
                relationship_type=_ref("relationship_type") or rel.relationship_type,
                employment_type=_ref("employment_type") or "",
                source_business_type=biz_type,
                source_business_id=biz_id,
                reason_code=case.reason_id.code,
            )
            rel.refresh_from_db()
            target_fact_ids.append(f"relationship:{rel.id}:v{rel.version}")

        elif action == ChangeActionCode.MANAGER_CHANGE:
            current_primary = _primary_assignment_as_of(
                self.tenant_id,
                case,
                eff,
            )
            if current_primary is None:
                raise ApplyServiceError(
                    "ASSIGNMENT_NOT_FOUND",
                    "生效日未找到可继承的当前主岗",
                )
            new_primary = assignment_service.switch_primary(
                employment_relationship_id=current_primary.employment_relationship_id,
                effective_from=eff,
                organization_id=current_primary.organization_id,
                position_id=current_primary.position_id,
                post_catalog_id=current_primary.post_catalog_id,
                legacy_department_id=current_primary.legacy_department_id,
                legacy_job_position_id=current_primary.legacy_job_position_id,
                assignment_role_code=current_primary.assignment_role_code,
                fte=current_primary.fte,
                reporting_staff_id=reporting_staff,
                source_business_type=biz_type,
                source_business_id=biz_id,
            )
            target_fact_ids.append(str(new_primary.id))

        elif action in (
            ChangeActionCode.TEMPORARY_SECONDMENT,
            ChangeActionCode.TEMPORARY_ATTACHMENT,
        ):
            temp_type = (
                "SECONDMENT"
                if action == ChangeActionCode.TEMPORARY_SECONDMENT
                else "TEMPORARY"
            )
            temp = assignment_service.create_assignment(
                employment_relationship_id=_current_rel(self.tenant_id, case, eff),
                assignment_type=temp_type,
                effective_from=eff,
                organization_id=target_org,
                position_id=target_pos,
                fte=_decimal_or_none(_ref("fte")) or 1,
                effective_to=_date_or_none(_ref("expected_return_at")),
                source_business_type=biz_type,
                source_business_id=biz_id,
            )
            source_assignment = _current_primary(self.tenant_id, case, eff)
            if source_assignment is None:
                raise ApplyServiceError(
                    "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                    "未找到原主岗",
                )
            from hr_changes.services.temporary_service import TemporaryAssignmentService

            TemporaryAssignmentService(self.tenant_id).create_link(
                change_case_id=case,
                source_assignment_id=source_assignment,
                temporary_assignment_id=temp,
                start_at=eff,
                expected_return_at=(
                    _date_or_none(_ref("expected_return_at")) or eff
                ),
            )
            target_fact_ids.append(str(temp.id))

        elif action == ChangeActionCode.RETURN_FROM_TEMPORARY:
            from hr_changes.services.return_service import ReturnService

            link = HrTemporaryAssignmentLink.objects.filter(
                tenant_id=self.tenant_id,
                change_case_id=case,
            ).first()
            if link is None:
                raise ApplyServiceError(
                    "CHANGE_NOT_FOUND",
                    "未找到对应临时异动关系",
                )
            ReturnService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ).execute_return(
                link.id,
                return_effective_at=eff,
                return_case_id=case.id,
            )
            link.refresh_from_db()
            target_fact_ids.extend(
                [
                    f"temporary-link:{link.id}",
                    f"assignment:{link.source_assignment_id_id}",
                    f"assignment:{link.temporary_assignment_id_id}",
                ]
            )

        # 下游 followup（总册 §4.3/4.5/4.6）
        followup = []
        if action in (
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
            ChangeActionCode.POST_CATEGORY_CHANGE,
            ChangeActionCode.EMPLOYEE_CATEGORY_CHANGE,
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
        ):
            followup.append(("HR15", "CompensationRecalculationRequested"))
            followup.append(("HR11", "AttendanceRuleReevaluationRequested"))
        if action in (
            ChangeActionCode.EMPLOYMENT_TYPE_CHANGE,
            ChangeActionCode.ORG_TRANSFER,
            ChangeActionCode.ORG_POSITION_TRANSFER,
        ):
            followup.append(("HR07", "ContractReviewRequired"))

        return {
            "source_fact_ids": source_fact_ids,
            "target_fact_ids": target_fact_ids,
            "position_changes": {
                "target_position": (
                    str(case.target_position_id_id)
                    if case.target_position_id_id
                    else ""
                ),
            },
            "followup": followup,
        }


# ---------------------------------------------------------------------------
def _current_rel(tenant_id, case, as_of):
    from hr_staff.services.effective_dated_query_service import (
        EffectiveDatedQueryService,
    )

    qs = EffectiveDatedQueryService(tenant_id)
    return qs.relationships_as_of(case.staff_master_id_id, as_of).first()


def _current_primary(tenant_id, case, as_of):
    from hr_staff.services.effective_dated_query_service import (
        EffectiveDatedQueryService,
    )

    return EffectiveDatedQueryService(tenant_id).primary_assignment_as_of(
        case.staff_master_id_id,
        as_of,
    )


def _primary_assignment_as_of(tenant_id, case, as_of):
    from hr_staff.services.effective_dated_query_service import (
        EffectiveDatedQueryService,
    )

    return EffectiveDatedQueryService(tenant_id).primary_assignment_as_of(
        case.staff_master_id_id,
        as_of,
    )


def _capture_facts(tenant_id, case, as_of) -> dict:
    from hr_staff.services.effective_dated_query_service import (
        EffectiveDatedQueryService,
    )

    qs = EffectiveDatedQueryService(tenant_id)
    primary = qs.primary_assignment_as_of(case.staff_master_id_id, as_of)
    staff = case.staff_master_id
    rel = qs.relationships_as_of(case.staff_master_id_id, as_of).first()
    return {
        "staffNo": staff.staff_no,
        "staffCategory": staff.staff_category_code,
        "organization": (
            primary.organization_id.stable_code
            if primary and primary.organization_id
            else ""
        ),
        "position": (
            primary.position_id.position_code
            if primary and primary.position_id
            else ""
        ),
        "relationshipType": rel.relationship_type if rel else "",
        "status": qs.status_as_of(case.staff_master_id_id, as_of),
    }


def _int_or_uuid(value):
    if value in (None, ""):
        return None
    return value


def _map_source_business_type(action_code: str) -> str:
    """HR06 动作代码 → HR03 VALID_ASSIGNMENT_SOURCES 白名单。"""
    TRANSFER_ACTIONS = frozenset(
        {
            "ORG_TRANSFER",
            "POSITION_TRANSFER",
            "ORG_POSITION_TRANSFER",
            "PRIMARY_ASSIGNMENT_SWITCH",
            "MANAGER_CHANGE",
        }
    )
    POSITION_ACTIONS = frozenset(
        {
            "POST_CATEGORY_CHANGE",
            "EMPLOYEE_CATEGORY_CHANGE",
            "EMPLOYMENT_TYPE_CHANGE",
            "ADD_SECONDARY_ASSIGNMENT",
            "END_SECONDARY_ASSIGNMENT",
            "TEMPORARY_SECONDMENT",
            "TEMPORARY_ATTACHMENT",
            "RETURN_FROM_TEMPORARY",
            "LOCATION_CHANGE",
        }
    )
    if action_code in TRANSFER_ACTIONS:
        return "HR06_TRANSFER"
    if action_code in POSITION_ACTIONS:
        return "HR06_POSITION_CHANGE"
    return "HR06_POSITION_CHANGE"


def _resolve_org(tenant_id, value):
    if value in (None, ""):
        return None
    from hr_structure.models import HrOrganization

    return HrOrganization.objects.filter(tenant_id=tenant_id, id=value).first()


def _resolve_position(tenant_id, value):
    if value in (None, ""):
        return None
    from hr_structure.models import HrPosition

    return HrPosition.objects.filter(tenant_id=tenant_id, id=value).first()


def _resolve_catalog(tenant_id, value):
    if value in (None, ""):
        return None
    from hr_structure.models import HrPostCatalogVersion

    return HrPostCatalogVersion.objects.filter(tenant_id=tenant_id, id=value).first()


def _resolve_staff(tenant_id, value):
    if value in (None, ""):
        return None
    from hr_staff.models import HrStaffMaster

    return HrStaffMaster.objects.filter(tenant_id=tenant_id, id=value).first()


def _decimal_or_none(value):
    if value in (None, ""):
        return None
    from decimal import Decimal, InvalidOperation

    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _date_or_none(value):
    if value in (None, ""):
        return None
    from django.utils.dateparse import parse_date

    return parse_date(value)
