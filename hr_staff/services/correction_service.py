"""
hr_staff/services/correction_service.py —— 更正状态机与影响分析（S9）。

状态机（总册 §15.3）：
DRAFT → SUBMITTED → UNDER_REVIEW → (RETURNED → RESUBMITTED) → APPROVED → APPLYING → APPLIED
                                                       ↘ REJECTED
                                                       ↘ CANCELLED

原则：
- RETURNED ≠ REJECTED；
- APPROVED 后应用失败必须 APPLYING/FAILED 可追踪，不允许审批成功但主档没改还显示 success；
- BUSINESS_PROCESS_ONLY 字段不可经更正绕过（FieldGovernancePolicy edit_mode 判定）；
- retroactive 影响分析：AFFECTS_CLOSED_PAYROLL / AFFECTS_ARCHIVED_ASSESSMENT / AFFECTS_REPORTED_DATA / HIGH_RISK_RETROACTIVE。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from hr_staff.constants import (
    CorrectionEditMode,
    CorrectionImpactLevel,
    CorrectionStatus,
)
from hr_staff.models import HrCorrectionCase, HrCorrectionItem, HrFieldGovernancePolicy
from hr_staff.policies import get_field_policy
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.common import resolve_staff


class CorrectionPolicyDenied(Exception):
    code = "CORRECTION_POLICY_DENIED"


class CorrectionStateError(Exception):
    code = "CORRECTION_STATE_INVALID"

    def __init__(self, message, code=None):
        super().__init__(message)
        if code is not None:
            self.code = code


class CorrectionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    def create_case(
        self,
        *,
        staff_id,
        reason: str,
        items: list[dict],
        evidence_material_id=None,
    ) -> HrCorrectionCase:
        """
        items: [{"field_code","fact_type","fact_id","old_value_masked","new_value_masked",
                 "effective_date","impact_level"}]
        校验：
          - 每个 field 必须在 FieldGovernancePolicy 注册；
          - BUSINESS_PROCESS_ONLY 字段 → CORRECTION_POLICY_DENIED（防绕过 #55 负向）；
          - required_evidence 且无 evidence → CORRECTION_POLICY_DENIED；
          - staff 必须属于当前 tenant（P1-6 跨租户防线）。
        """
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-1 UUID/实例归一 + P1-6
        policy_map = self._policy_map()
        for attempt in range(3):  # P2：并发撞 case_no 重试
            try:
                return self._create_case_once(staff, policy_map, reason, items, evidence_material_id)
            except IntegrityError:
                if attempt == 2:
                    raise
                continue

    @transaction.atomic
    def _create_case_once(self, staff, policy_map, reason, items, evidence_material_id) -> HrCorrectionCase:
        case_no = self._next_case_no()
        case = HrCorrectionCase.objects.create(
            case_no=case_no,
            tenant_id=self.tenant_id,
            staff_id=staff,
            reason=reason,
            evidence_material_id=evidence_material_id,
            status=CorrectionStatus.DRAFT,
        )
        for item in items:
            field_code = item["field_code"]
            policy = policy_map.get(field_code) or get_field_policy(field_code)
            if policy is None:
                raise CorrectionPolicyDenied(f"字段未登记治理策略: {field_code}")
            if policy.edit_mode == CorrectionEditMode.BUSINESS_PROCESS_ONLY:
                raise CorrectionPolicyDenied(f"{field_code} 仅能由正式业务流程变更，禁止经更正修改")
            if policy.required_evidence and not evidence_material_id:
                raise CorrectionPolicyDenied(f"{field_code} 要求提供证据材料")
            impact = item.get("impact_level") or self.impact_for(field_code, item.get("effective_date"))
            HrCorrectionItem.objects.create(
                tenant_id=self.tenant_id,
                case_id=case,
                fact_type=item.get("fact_type", ""),
                fact_id=item.get("fact_id"),
                field_code=field_code,
                old_value_masked=item.get("old_value_masked", ""),
                new_value_masked=item.get("new_value_masked", ""),
                old_value_ref=item.get("old_value_ref", ""),
                new_value_ref=item.get("new_value_ref", ""),
                effective_date=item.get("effective_date"),
                impact_level=impact,
            )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="CorrectionDrafted",
            actor_user_id=self.actor_user_id,
            staff_id=staff.id,
            business_type="CORRECTION",
            business_id=str(case.id),
            reason=reason,
        )
        return case

    def _policy_map(self) -> dict:
        return {
            p.field_code: p
            for p in HrFieldGovernancePolicy.objects.filter(tenant_id=self.tenant_id, is_enabled=True)
        }

    def _next_case_no(self) -> str:
        # COR-YYYYMMDD-NNNN；幂等：事务内用 max 前缀
        import datetime

        prefix = f"COR-{datetime.date.today().strftime('%Y%m%d')}"
        last = (
            HrCorrectionCase.objects.filter(tenant_id=self.tenant_id, case_no__startswith=prefix)
            .order_by("-case_no")
            .values_list("case_no", flat=True)
            .first()
        )
        seq = 1
        if last:
            try:
                seq = int(last.rsplit("-", 1)[-1]) + 1
            except ValueError:
                seq = 1
        return f"{prefix}-{seq:04d}"

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------
    def _assert_status(self, case: HrCorrectionCase, expected):
        if case.status != expected:
            raise CorrectionStateError(
                f"当前状态 {case.status} 不允许执行该操作（期望 {expected}）"
            )

    def _audit(self, case, action: str, extra: str = ""):
        """P1-g：更正状态迁移审计（§28.2）。"""
        write_audit_event(
            tenant_id=self.tenant_id,
            action=action,
            actor_user_id=self.actor_user_id,
            staff_id=case.staff_id_id,
            business_type="CORRECTION",
            business_id=str(case.id),
            reason=f"case={case.case_no} {extra}".strip(),
        )

    @transaction.atomic
    def submit(self, case_id):
        case = self._get(case_id)
        self._assert_status(case, CorrectionStatus.DRAFT)
        case.status = CorrectionStatus.SUBMITTED
        case.submitted_by = self.actor_user_id
        case.submitted_at = timezone.now()
        case.save()
        self._audit(case, "CorrectionSubmitted")
        return case

    @transaction.atomic
    def review(self, case_id):
        case = self._get(case_id)
        self._assert_status(case, CorrectionStatus.SUBMITTED)
        case.status = CorrectionStatus.UNDER_REVIEW
        case.reviewed_by = self.actor_user_id
        case.reviewed_at = timezone.now()
        case.save()
        self._audit(case, "CorrectionUnderReview")
        return case

    @transaction.atomic
    def return_(self, case_id, reason: str):
        case = self._get(case_id)
        if case.status not in (CorrectionStatus.UNDER_REVIEW, CorrectionStatus.SUBMITTED):
            raise CorrectionStateError("仅 UNDER_REVIEW/SUBMITTED 可退回")
        case.status = CorrectionStatus.RETURNED
        case.return_reason = reason
        case.save()
        self._audit(case, "CorrectionReturned", f"reason={reason[:200]}")
        return case

    @transaction.atomic
    def resubmit(self, case_id):
        case = self._get(case_id)
        self._assert_status(case, CorrectionStatus.RETURNED)
        case.status = CorrectionStatus.RESUBMITTED
        case.save()
        self._audit(case, "CorrectionResubmitted")
        return case

    @transaction.atomic
    def approve(self, case_id, approve_high_risk: bool = False):
        case = self._get(case_id)
        if case.status not in (CorrectionStatus.UNDER_REVIEW, CorrectionStatus.RESUBMITTED):
            raise CorrectionStateError("仅 UNDER_REVIEW/RESUBMITTED 可审批")
        case.refresh_from_db()
        impact = self._max_impact(case)
        if impact in (
            CorrectionImpactLevel.AFFECTS_CLOSED_PAYROLL,
            CorrectionImpactLevel.AFFECTS_ARCHIVED_ASSESSMENT,
            CorrectionImpactLevel.AFFECTS_REPORTED_DATA,
            CorrectionImpactLevel.HIGH_RISK_RETROACTIVE,
        ) and not approve_high_risk:
            raise CorrectionPolicyDenied("高风险追溯更正需要 HR_DIRECTOR 审批权限")
        case.status = CorrectionStatus.APPROVED
        case.approved_by = self.actor_user_id
        case.approved_at = timezone.now()
        case.impact_level = impact
        case.save()
        self._audit(case, "CorrectionApproved", f"impact={impact}")
        return case

    @transaction.atomic
    def reject(self, case_id, reason: str):
        case = self._get(case_id)
        if case.status not in (CorrectionStatus.UNDER_REVIEW, CorrectionStatus.RESUBMITTED):
            raise CorrectionStateError("仅 UNDER_REVIEW/RESUBMITTED 可拒绝")
        case.status = CorrectionStatus.REJECTED
        case.reject_reason = reason
        case.save()
        self._audit(case, "CorrectionRejected", f"reason={reason[:200]}")
        return case

    @transaction.atomic
    def cancel(self, case_id):
        case = self._get(case_id)
        if case.status not in (
            CorrectionStatus.DRAFT,
            CorrectionStatus.SUBMITTED,
            CorrectionStatus.UNDER_REVIEW,
            CorrectionStatus.RETURNED,
        ):
            raise CorrectionStateError("当前状态不可取消")
        case.status = CorrectionStatus.CANCELLED
        case.save()
        self._audit(case, "CorrectionCancelled")
        return case

    # ------------------------------------------------------------------
    # 应用（APPLYING → APPLIED / FAILED，幂等重试 + 乐观锁）
    # ------------------------------------------------------------------
    def apply(self, case_id, apply_fn=None, expected_version=None):
        """
        应用更正。apply_fn 负责真正写 authority；默认使用内置应用器（P1-3 修复）。
        乐观锁：expected_version 不匹配 → VERSION_CONFLICT（409）。
        失败必须把 case 置 FAILED 并记录 apply_error，不允许"审批成功但主档没改还显示 success"。

        事务结构：
          [原子块1] 锁 case + 状态/版本校验（通过即释放 savepoint）
          [原子块2] 应用主逻辑（APPLYING → apply_fn → APPLIED + version+1）
          异常时：FAILED 用独立 update() 落库（块2 回滚不影响），再抛 CORRECTION_APPLY_FAILED
        """
        case = None
        application_started = False
        try:
            with transaction.atomic():
                case = HrCorrectionCase.objects.select_for_update().get(
                    tenant_id=self.tenant_id, id=case_id
                )
                self._assert_status(case, CorrectionStatus.APPROVED)
                if expected_version is not None and case.version != expected_version:
                    raise CorrectionStateError(
                        "VERSION_CONFLICT: 更正已过期，请刷新后重试",
                        code="VERSION_CONFLICT",
                    )
                case.status = CorrectionStatus.APPLYING
                case.save(update_fields=["status"])
                application_started = True
                if apply_fn is None:
                    apply_fn = self._default_apply
                apply_fn(case)
                case.status = CorrectionStatus.APPLIED
                case.applied_at = timezone.now()
                case.apply_error = ""
                case.version += 1
                case.save(update_fields=["status", "applied_at", "apply_error", "version"])
                HrCorrectionItem.objects.filter(
                    tenant_id=self.tenant_id, case_id=case
                ).update(applied=True)
                from hr_staff.services.outbox_service import staff_basic_info_corrected

                fields = list(case.items.values_list("field_code", flat=True))
                staff_basic_info_corrected(
                    self.tenant_id, case.staff_id_id, case.id, fields
                )
        except Exception as exc:  # 应用失败必须可追踪（独立落库，不被块2回滚）
            if not application_started or case is None:
                raise
            HrCorrectionCase.objects.filter(pk=case.pk).update(
                status=CorrectionStatus.FAILED,
                apply_error=f"{exc.__class__.__name__}: {exc}",
            )
            write_audit_event(
                tenant_id=self.tenant_id,
                action="CorrectionApplyFailed",
                actor_user_id=self.actor_user_id,
                staff_id=case.staff_id_id,
                business_type="CORRECTION",
                business_id=str(case.id),
                reason=str(exc)[:500],
            )
            raise CorrectionStateError(f"CORRECTION_APPLY_FAILED: {exc}")
        write_audit_event(
            tenant_id=self.tenant_id,
            action="CorrectionApplied",
            actor_user_id=self.actor_user_id,
            staff_id=case.staff_id_id,
            business_type="CORRECTION",
            business_id=str(case.id),
        )
        case.refresh_from_db()
        return case

    def _default_apply(self, case):
        """内置应用器：按 field_code 写 authority（V1 支持 person/contact 类字段）。

        每个未应用 item 逐项应用；某项失败整体抛错（由 apply 捕获置 FAILED）。
        身份证明文等需重新加密的高敏字段 → 明确抛错要求显式应用器，禁止静默。
        """
        for item in case.items.filter(applied=False):
            self._apply_item(case, item)

    def _apply_item(self, case: HrCorrectionCase, item):
        """按 field_code 应用单个更正 item。"""
        from hr_staff.services.correction_fields import get_correction_field_handler

        get_correction_field_handler(item.field_code).apply(self, case, item)

    @staticmethod
    def _upsert_contact(staff, kind: str, value: str):
        from hr_staff.models import HrPersonContact

        contact = HrPersonContact.objects.filter(
            tenant_id=staff.tenant_id,
            person_id=staff.person_id,
            contact_kind=kind,
        ).first()
        masked = HrPersonContact.mask_value(kind, value or "")
        if contact:
            contact.contact_value = value or ""
            contact.masked_display = masked
            contact.save(update_fields=["contact_value", "masked_display", "updated_at"])
        elif value:
            HrPersonContact.objects.create(
                tenant_id=staff.tenant_id,
                person_id=staff.person_id,
                contact_kind=kind,
                contact_value=value,
                masked_display=masked,
            )

    # ------------------------------------------------------------------
    # 影响分析
    # ------------------------------------------------------------------
    @staticmethod
    def impact_for(field_code: str, effective_date: Optional[date]) -> str:
        """按字段与生效日期给出影响等级（V1 静态规则）。"""
        policy = get_field_policy(field_code)
        if policy and policy.business_process_only:
            return CorrectionImpactLevel.NO_DOWNSTREAM_IMPACT  # 实际上会先被拒绝
        high_risk_fields = {
            "staff.staff_no",
            "identity.document_number",
            "person.birth_date",
        }
        if field_code in high_risk_fields:
            return CorrectionImpactLevel.HIGH_RISK_RETROACTIVE
        if field_code in ("employment.effective_from", "employment.effective_to"):
            return CorrectionImpactLevel.REQUIRES_DASHBOARD_RECALC
        return CorrectionImpactLevel.NO_DOWNSTREAM_IMPACT

    def _max_impact(self, case: HrCorrectionCase) -> str:
        order = [
            CorrectionImpactLevel.HIGH_RISK_RETROACTIVE,
            CorrectionImpactLevel.AFFECTS_REPORTED_DATA,
            CorrectionImpactLevel.AFFECTS_ARCHIVED_ASSESSMENT,
            CorrectionImpactLevel.AFFECTS_CLOSED_PAYROLL,
            CorrectionImpactLevel.REQUIRES_DASHBOARD_RECALC,
            CorrectionImpactLevel.REQUIRES_REINDEX,
            CorrectionImpactLevel.NO_DOWNSTREAM_IMPACT,
        ]
        impacts = set(case.items.values_list("impact_level", flat=True))
        for level in order:
            if level in impacts:
                return level
        return CorrectionImpactLevel.NO_DOWNSTREAM_IMPACT

    def _get(self, case_id) -> HrCorrectionCase:
        case = HrCorrectionCase.objects.filter(
            tenant_id=self.tenant_id, id=case_id
        ).prefetch_related("items").first()
        if case is None:
            raise CorrectionStateError("CORRECTION_NOT_FOUND")
        return case
