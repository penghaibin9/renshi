"""
hr_onboarding/services/activation_service.py

ActivateOnboardingCase —— HR05 正式生效闸门（总册 §10.6，00 §92）。

事务内（全部真实调用，依赖已就绪）：
  1. SELECT ... FOR UPDATE onboarding_case
  2. 再次检查状态（幂等：已 ACTIVE/成功尝试 → 返回原结果）
  3. Activation Gate 全项
  4. HR03 match_or_create_person
  5. HR03 create StaffMaster（工号由 HR03 分配）
  6. HR03 create EmploymentRelationship（effective_from=effective_at）
  7. HR03 create primary Assignment
  8. HR02 commit reservation（HELD→COMMITTED）
  9. 写 HrOnboardingActivationSnapshot
  10. outbox enqueue StaffActivated（同事务）
  11. case → ACTIVE + activation_status SUCCEEDED

硬规则：
- 不要在同一数据库事务里同步等待外部 SSO/邮箱/门禁（§10.6）；
- 外部 provisioning 失败不回滚 HR 事实（S6 provisioning 独立）；
- 转正失败走正式人事事件，不 Employee.is_active=False（S7）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    ActivationAlreadyCompletedError,
    Hr05ApiError,
    PositionReservationInvalidError,
    TenantContextRequiredError,
)
from hr_onboarding.constants import ActivationStatus, CaseStatus
from hr_onboarding.integrations.hr02 import Hr02PositionProvider
from hr_onboarding.integrations.hr03 import Hr03ActivationProvider, Hr03ActivationProviderError
from hr_onboarding.models import (
    HrActivationAttempt,
    HrOnboardingActivationSnapshot,
    HrOnboardingCase,
    HrOnboardingStageTransition,
)
from hr_onboarding.policies.activation_policy import evaluate_activation_gate
from hr_onboarding.policies.idempotency import apply_idempotency, normalize_key, store_result
from hr_onboarding.policies.state_machine import assert_case_transition
from hr_onboarding.services.outbox_service import enqueue_outbox

logger = logging.getLogger(__name__)

STAFF_ACTIVATED_EVENT = "StaffActivated"


class ActivationService:
    def __init__(
        self,
        *,
        tenant_id: int,
        actor_user_id: Optional[int] = None,
        hr03_provider: Optional[Hr03ActivationProvider] = None,
        hr02_provider_factory=None,
    ):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.hr03 = hr03_provider or Hr03ActivationProvider()
        self._hr02_factory = hr02_provider_factory or (lambda: Hr02PositionProvider(tenant_id))

    def _assert_case_tenant(self, case: HrOnboardingCase) -> None:
        if getattr(case, "tenant_id", None) != self.tenant_id:
            raise TenantContextRequiredError("入职案件不属于当前学校")

    # ------------------------------------------------------------------
    # 查询 Gate（只读，供 UI）
    # ------------------------------------------------------------------
    def gate(self, case: HrOnboardingCase, *, effective_at: date, extra_policy_checks=None):
        self._assert_case_tenant(case)
        return evaluate_activation_gate(
            tenant_id=self.tenant_id,
            case=case,
            effective_at=effective_at,
            extra_policy_checks=extra_policy_checks,
        )

    # ------------------------------------------------------------------
    # ActivateOnboardingCase 领域命令
    # ------------------------------------------------------------------
    @transaction.atomic
    def activate(
        self,
        case: HrOnboardingCase,
        *,
        effective_at: date,
        idempotency_key: str,
        extra_policy_checks: Optional[list[dict]] = None,
    ) -> dict:
        # 任何幂等查询之前先验证案件 tenant，防止跨学校 idempotency replay 泄露结果。
        self._assert_case_tenant(case)
        key = normalize_key(
            idempotency_key,
            namespace=f"hr05:activate:tenant:{self.tenant_id}",
        )
        replay = apply_idempotency(key)
        if replay is not None:
            return replay

        # 幂等：同 tenant + idempotency_key 已成功执行 → 返回原结果。
        existing_attempt = HrActivationAttempt.objects.filter(
            tenant_id=self.tenant_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing_attempt is not None and existing_attempt.status == ActivationStatus.SUCCEEDED:
            result = self._build_result(case, existing_attempt)
            store_result(key, result)
            return result

        case = (
            HrOnboardingCase.objects.select_for_update()
            .filter(id=case.id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise TenantContextRequiredError("入职案件不属于当前学校")

        # 已 ACTIVE → 返回原结果（不重复激活）
        if case.status in (
            CaseStatus.ACTIVE,
            CaseStatus.ONBOARDING_IN_PROGRESS,
            CaseStatus.ONBOARDING_COMPLETED,
            CaseStatus.PROBATION,
            CaseStatus.CONFIRMED,
        ):
            attempt = HrActivationAttempt.objects.filter(
                tenant_id=self.tenant_id,
                case=case,
                status=ActivationStatus.SUCCEEDED,
            ).first()
            result = self._build_result(case, attempt)
            store_result(key, result)
            return result

        # 状态可达性先校验（非法状态迁移优先报错）
        assert_case_transition(case.status, CaseStatus.ACTIVATING)
        from_stage = case.status

        # Gate 全项
        gate_result = self.gate(
            case,
            effective_at=effective_at,
            extra_policy_checks=extra_policy_checks,
        )
        if not gate_result.passed:
            failed = [item.code for item in gate_result.items if not item.ok]
            raise Hr05ApiError(
                f"Activation Gate 未通过: {failed}",
                details={"failedItems": failed},
            )

        # 状态推进到 ACTIVATING
        case.status = CaseStatus.ACTIVATING
        case.activation_status = ActivationStatus.IN_PROGRESS
        case.save(update_fields=["status", "activation_status", "updated_at"])

        attempt = HrActivationAttempt.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            effective_at=effective_at,
            idempotency_key=idempotency_key,
            status=ActivationStatus.IN_PROGRESS,
        )

        # HR03 四步 + HR02 commit 包在 savepoint 内：
        # 任一失败 → savepoint 回滚（HR03 部分写入不残留），
        # 但外层事务继续保存 FAILED 状态（不 raise 触发外层回滚）。
        profile = None
        if hasattr(case, "prehire_profile"):
            try:
                profile = case.prehire_profile
            except Exception:
                profile = None
        try:
            with transaction.atomic():
                # 4) Person
                person = self.hr03.match_or_create_person(
                    tenant_id=self.tenant_id,
                    legal_name=(profile.legal_name if profile else ""),
                    preferred_name=(profile.preferred_name if profile else ""),
                )
                # 5) StaffMaster（工号 HR03 分配）
                staff = self.hr03.create_staff_master(
                    tenant_id=self.tenant_id,
                    person_id=person.id,
                    staff_category_code=case.staff_category,
                    legacy_employee_id=case.candidate_id,
                )
                # 6) EmploymentRelationship
                employment = self.hr03.create_employment(
                    tenant_id=self.tenant_id,
                    staff_id=staff,
                    employment_type=case.employment_type,
                    effective_from=effective_at,
                    source_business_id=str(case.id),
                    reason_code="ONBOARDING",
                )
                # 7) 主岗 Assignment（HR02 capacity 由 HR03 policy 校验）
                #     case.planned_post_catalog_id 指向 HrPostCatalog（目录），
                #     HR03 assignment 需要 HrPostCatalogVersion → 按 effective_at 解析。
                post_catalog_version_id = None
                if case.planned_post_catalog_id_id:
                    from hr_structure.selectors import effective as hr02_effective

                    catalog_version = hr02_effective.post_catalog_version_as_of(
                        self.tenant_id,
                        case.planned_post_catalog_id_id,
                        effective_at,
                    )
                    post_catalog_version_id = catalog_version.id if catalog_version else None
                assignment = self.hr03.create_assignment(
                    tenant_id=self.tenant_id,
                    employment_relationship_id=employment.id,
                    assignment_type="PRIMARY",
                    effective_from=effective_at,
                    organization_id=case.planned_organization_id_id,
                    position_id=case.planned_position_id_id,
                    post_catalog_id=post_catalog_version_id,
                    fte=1.0,
                    source_business_id=str(case.id),
                )
                # 8) HR02 commit reservation（HELD→COMMITTED，只在 HR03 生效后）
                if case.position_reservation_id_id:
                    hr02 = self._hr02_factory()
                    if not hr02.check_valid(case.position_reservation_id_id):
                        raise PositionReservationInvalidError("岗位预占已失效，无法提交")
                    hr02.commit(case.position_reservation_id_id)
        except (Hr03ActivationProviderError, PositionReservationInvalidError) as exc:
            code = getattr(exc, "code", "ACTIVATION_FAILED")
            # savepoint 已回滚 HR03 部分副作用；此处记录失败状态（外层事务保留）
            attempt.status = ActivationStatus.FAILED
            attempt.result_json = {"error": code, "message": str(exc)}
            attempt.save(update_fields=["status", "result_json"])
            case.status = CaseStatus.ACTIVATION_FAILED
            case.activation_status = ActivationStatus.FAILED
            case.save(update_fields=["status", "activation_status", "updated_at"])
            HrOnboardingStageTransition.objects.create(
                tenant_id=self.tenant_id,
                case=case,
                from_stage=CaseStatus.ACTIVATING,
                to_stage=CaseStatus.ACTIVATION_FAILED,
                action="ACTIVATE_FAILED",
                actor_user_id=self.actor_user_id,
                reason=str(exc),
            )
            failure = {
                "case_id": str(case.id),
                "case_status": case.status,
                "activation_status": case.activation_status,
                "activated": False,
                "error": code,
            }
            store_result(key, failure)
            return failure
        except Exception as exc:  # 未知异常：不假报成功，记录后按失败处理
            logger.exception("activate unexpected error case=%s", case.id)
            attempt.status = ActivationStatus.FAILED
            attempt.result_json = {"error": "ACTIVATION_FAILED", "message": str(exc)}
            attempt.save(update_fields=["status", "result_json"])
            case.status = CaseStatus.ACTIVATION_FAILED
            case.activation_status = ActivationStatus.FAILED
            case.save(update_fields=["status", "activation_status", "updated_at"])
            failure = {
                "case_id": str(case.id),
                "case_status": case.status,
                "activation_status": case.activation_status,
                "activated": False,
                "error": "ACTIVATION_FAILED",
            }
            store_result(key, failure)
            return failure

        # 9) Activation Snapshot
        snapshot = HrOnboardingActivationSnapshot.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            activated_at=timezone.now(),
            person_id=person.id,
            staff_master_id=staff.id,
            employment_id=employment.id,
            assignment_id=assignment.id,
            staff_no=getattr(staff, "staff_no", "") or "",
            organization_id=case.planned_organization_id_id,
            position_id=case.planned_position_id_id,
            source_versions_json={"case_version": case.version, "handoff": case.source_id},
        )

        # 10) outbox StaffActivated（同事务）
        enqueue_outbox(
            tenant_id=self.tenant_id,
            event_type=STAFF_ACTIVATED_EVENT,
            aggregate_type="HrOnboardingCase",
            aggregate_id=str(case.id),
            correlation_id=str(case.id),
            payload={
                "case_id": str(case.id),
                "staff_master_id": str(staff.id),
                "staff_no": getattr(staff, "staff_no", "") or "",
                "effective_at": effective_at.isoformat(),
            },
        )

        # 11) case → ACTIVE
        case.status = CaseStatus.ACTIVE
        case.activation_status = ActivationStatus.SUCCEEDED
        case.hr03_person_id = person.id
        case.hr03_staff_master_id = staff.id
        case.hr03_employment_id = employment.id
        case.hr03_assignment_id = assignment.id
        case.version += 1
        case.save(
            update_fields=[
                "status",
                "activation_status",
                "hr03_person_id",
                "hr03_staff_master_id",
                "hr03_employment_id",
                "hr03_assignment_id",
                "version",
                "updated_at",
            ]
        )
        HrOnboardingStageTransition.objects.create(
            tenant_id=self.tenant_id,
            case=case,
            from_stage=from_stage,
            to_stage=CaseStatus.ACTIVE,
            action="ACTIVATE",
            actor_user_id=self.actor_user_id,
            reason="正式生效闸门通过",
        )

        attempt.status = ActivationStatus.SUCCEEDED
        attempt.snapshot_ref = snapshot.id
        attempt.result_json = {"staff_no": getattr(staff, "staff_no", "") or ""}
        attempt.save(update_fields=["status", "snapshot_ref", "result_json"])

        # 激活成功后：实例化协同任务（模板→实例），并请求核心 provisioning
        try:
            from hr_onboarding.services.task_service import TaskService

            TaskService(tenant_id=self.tenant_id).instantiate_tasks(case)
        except Exception:
            logger.exception("instantiate_tasks failed after activation case=%s", case.id)
            # 不阻断激活：任务缺失属协同欠账，进入协同中心可见

        result = {
            "case_id": str(case.id),
            "case_status": case.status,
            "activation_status": case.activation_status,
            "person_id": str(person.id),
            "staff_master_id": str(staff.id),
            "employment_id": str(employment.id),
            "assignment_id": str(assignment.id),
            "staff_no": getattr(staff, "staff_no", "") or "",
            "activated": True,
        }
        store_result(key, result)
        return result

    def _build_result(self, case: HrOnboardingCase, attempt: Optional[HrActivationAttempt]) -> dict:
        self._assert_case_tenant(case)
        snapshot = HrOnboardingActivationSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            case=case,
        ).first()
        return {
            "case_id": str(case.id),
            "case_status": case.status,
            "activation_status": case.activation_status,
            "staff_master_id": str(case.hr03_staff_master_id) if case.hr03_staff_master_id else None,
            "staff_no": snapshot.staff_no if snapshot else "",
            "activated": case.activation_status == ActivationStatus.SUCCEEDED,
        }
