"""
hr_changes/services/temporary_service.py —— 借调挂职服务（S6，总册 §27/§29）。

- start_temporary：建立临时异动（link + 按 source_policy 处理原岗）；
- extend：延期（保存 old/new + reason + 审批状态，不直接覆盖 expected_return_at）；
- apply_extension：审批后应用延期；
- due_soon / overdue：返岗提醒与超期检测。

实际任职段写入由 S8 Apply Service 调 HR03 完成；本服务管理临时异动关系结构。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr_changes.constants import ChangeActionCode, SourceAssignmentPolicy
from hr_changes.models import HrTemporaryAssignmentExtension, HrTemporaryAssignmentLink


class TemporaryServiceError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class TemporaryAssignmentService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    def _get_link_or_deny(self, link_id) -> HrTemporaryAssignmentLink:
        link = (
            HrTemporaryAssignmentLink.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=link_id)
            .first()
        )
        if link is None:
            raise TemporaryServiceError("CHANGE_NOT_FOUND", "临时异动关系不存在")
        return link

    @transaction.atomic
    def create_temporary_case(
        self,
        *,
        staff_master_id,
        action_id,
        reason_id,
        target_org_id,
        requested_effective_at,
        expected_return_at,
        source_policy: str = SourceAssignmentPolicy.KEEP_ACTIVE,
        target_position_id=None,
        fte=None,
        priority: str = "NORMAL",
    ):
        """建立可审批的借调/挂职 DRAFT；任职与 link 只在 Apply 时写入。"""
        from hr_changes.services.change_service import (
            ChangeService,
            ChangeServiceError,
            _parse_effective_date,
        )
        from hr_changes.services.transfer_service import _load_action_safe
        from hr_staff.services.effective_dated_query_service import (
            EffectiveDatedQueryService,
        )

        action = _load_action_safe(self.tenant_id, action_id)
        if action.code not in (
            ChangeActionCode.TEMPORARY_SECONDMENT,
            ChangeActionCode.TEMPORARY_ATTACHMENT,
        ):
            raise TemporaryServiceError(
                "CHANGE_INVALID_ACTION",
                "仅支持借调或挂职专用创建动作",
            )
        if source_policy != SourceAssignmentPolicy.KEEP_ACTIVE:
            raise TemporaryServiceError(
                "CHANGE_INVALID_ACTION",
                "当前仅开放原岗保持有效（KEEP_ACTIVE）策略",
            )
        if target_org_id in (None, ""):
            raise TemporaryServiceError(
                "CHANGE_INVALID_PAYLOAD",
                "借调挂职必须选择 HR02 目标组织",
            )
        target_org_ref = getattr(target_org_id, "pk", target_org_id)
        target_position = None
        if target_position_id not in (None, ""):
            from hr_structure.models import HrPosition

            target_position_ref = getattr(target_position_id, "pk", target_position_id)
            target_position = HrPosition.objects.filter(
                tenant_id=self.tenant_id,
                id=target_position_ref,
                organization_id_id=target_org_ref,
                lifecycle_status="ACTIVE",
            ).first()
            if target_position is None:
                raise TemporaryServiceError(
                    "CHANGE_TARGET_POSITION_INVALID",
                    "临时岗位必须属于所选单位且处于在用状态",
                )

        effective_at = _parse_effective_date(requested_effective_at)
        return_at = _parse_effective_date(expected_return_at)
        if return_at <= effective_at:
            raise TemporaryServiceError(
                "CHANGE_EFFECTIVE_DATE_INVALID",
                "预计返岗日必须晚于计划生效日",
            )
        staff_id = getattr(staff_master_id, "pk", staff_master_id)
        # 临时任职按计划生效日核验原岗，而不是按“今天”判断。
        # 否则未来生效的借调可能在申请时通过，但在真正 Apply 时找不到同一事实。
        source_assignment = EffectiveDatedQueryService(
            self.tenant_id
        ).primary_assignment_as_of(staff_id, effective_at)
        if source_assignment is None:
            raise ChangeServiceError(
                "CHANGE_SOURCE_ASSIGNMENT_MISMATCH",
                "计划生效日未找到可核验的 HR03 主岗",
            )

        # KEEP_ACTIVE 会保留原岗，因此必须在创建草稿时就核对同一聘用关系的
        # FTE 剩余额度。不能等审批完成后才由 HR03 拒绝，也不能为了走通流程
        # 删除既有 1.50 上限。调用方可明确给出 FTE；未给出时采用不超过 0.50
        # 的保守建议值，并受真实剩余额度继续约束。
        from hr_staff.models import HrStaffAssignment
        from hr_staff.policies.assignment_policy import AssignmentPolicy

        rel_id = source_assignment.employment_relationship_id_id
        active_rows = (
            HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                employment_relationship_id=rel_id,
                effective_from__lte=effective_at,
            )
            .exclude(status__in=("DRAFT", "CANCELLED"))
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_at))
            .values_list("fte", flat=True)
        )
        existing_total = sum((Decimal(str(value)) for value in active_rows), Decimal("0"))
        max_total = AssignmentPolicy(self.tenant_id).max_total_fte
        available_fte = max_total - existing_total
        if available_fte <= 0:
            raise TemporaryServiceError(
                "CHANGE_TEMPORARY_FTE_UNAVAILABLE",
                f"计划生效日当前任职 FTE 已达 {existing_total}，无临时任职额度；请先调整原岗/兼岗安排",
            )
        if fte in (None, ""):
            # Preserve the assignment model's existing 1.00 default as far as
            # the real remaining capacity allows; do not invent a new lower
            # school policy. A 1.00 primary therefore naturally yields 0.50.
            temporary_fte = min(Decimal("1.00"), available_fte)
        else:
            try:
                temporary_fte = Decimal(str(fte))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise TemporaryServiceError(
                    "CHANGE_INVALID_PAYLOAD", "临时任职 FTE 必须是有效数字"
                ) from exc
        if temporary_fte <= 0 or temporary_fte > available_fte:
            raise TemporaryServiceError(
                "CHANGE_TEMPORARY_FTE_EXCEEDED",
                f"临时任职 FTE 必须大于 0 且不超过当前剩余额度 {available_fte}",
            )

        return ChangeService(
            self.tenant_id,
            actor_user_id=self.actor_user_id,
        ).create_case(
            staff_master_id=staff_master_id,
            action_id=action,
            reason_id=reason_id,
            requested_effective_at=effective_at,
            proposals=[
                {
                    "domain": "assignment",
                    "field_code": "organization",
                    "proposed_value_ref": str(target_org_ref),
                },
                {
                    "domain": "temporary",
                    "field_code": "expected_return_at",
                    "proposed_value_ref": return_at.isoformat(),
                },
                {
                    "domain": "temporary",
                    "field_code": "source_policy",
                    "proposed_value_ref": SourceAssignmentPolicy.KEEP_ACTIVE,
                },
                {
                    "domain": "assignment",
                    "field_code": "fte",
                    "proposed_value_ref": str(temporary_fte),
                    "proposed_value_display": str(temporary_fte),
                },
                *(
                    [
                        {
                            "domain": "assignment",
                            "field_code": "position",
                            "proposed_value_ref": str(target_position.id),
                            "proposed_value_display": target_position.position_code,
                        },
                        {
                            "domain": "assignment",
                            "field_code": "post_catalog",
                            "proposed_value_ref": str(target_position.post_catalog_version_id_id),
                            "proposed_value_display": target_position.post_catalog_version_id.name,
                        },
                    ]
                    if target_position
                    else []
                ),
            ],
            source_org_id=source_assignment.organization_id,
            source_position_id=source_assignment.position_id,
            source_assignment_id=source_assignment,
            target_org_id=target_org_id,
            target_position_id=target_position,
            priority=priority,
        )

    @transaction.atomic
    def create_link(
        self,
        *,
        change_case_id,
        source_assignment_id,
        temporary_assignment_id,
        start_at: date,
        expected_return_at: date,
        source_policy: str = SourceAssignmentPolicy.KEEP_ACTIVE,
        return_policy_json: Optional[dict] = None,
    ) -> HrTemporaryAssignmentLink:
        if expected_return_at <= start_at:
            raise TemporaryServiceError(
                "CHANGE_EFFECTIVE_DATE_INVALID", "预计返岗日必须晚于开始日"
            )
        return HrTemporaryAssignmentLink.objects.create(
            tenant_id=self.tenant_id,
            change_case_id=change_case_id,
            source_assignment_id=source_assignment_id,
            temporary_assignment_id=temporary_assignment_id,
            start_at=start_at,
            expected_return_at=expected_return_at,
            source_assignment_status_policy=source_policy,
            return_policy_json=return_policy_json or {},
        )

    # ------------------------------------------------------------------
    # 延期（总册 §29）：不直接覆盖 expected_return_at
    # ------------------------------------------------------------------
    @transaction.atomic
    def extend(
        self,
        *,
        link_id,
        new_return_at: date,
        reason: str = "",
        apply_immediately: bool = True,
    ) -> HrTemporaryAssignmentExtension:
        link = self._get_link_or_deny(link_id)
        if link.status not in ("ACTIVE", "EXTENDED"):
            raise TemporaryServiceError(
                "CHANGE_INVALID_STATE", "仅生效中的临时异动可延期"
            )
        if new_return_at <= link.expected_return_at:
            raise TemporaryServiceError(
                "CHANGE_EFFECTIVE_DATE_INVALID", "延期后的返岗日必须晚于当前预计返岗日"
            )
        extension = HrTemporaryAssignmentExtension.objects.create(
            tenant_id=self.tenant_id,
            link_id=link,
            old_return_at=link.expected_return_at,
            new_return_at=new_return_at,
            reason=reason,
            requested_by=self.actor_user_id,
            status="APPROVED" if apply_immediately else "PENDING",
        )
        if apply_immediately:
            self.apply_extension(extension)
        return extension

    @transaction.atomic
    def apply_extension(self, extension: HrTemporaryAssignmentExtension) -> HrTemporaryAssignmentLink:
        link = self._get_link_or_deny(extension.link_id_id)
        if extension.status != "APPROVED":
            raise TemporaryServiceError(
                "CHANGE_INVALID_STATE", "延期需先审批"
            )
        link.expected_return_at = extension.new_return_at
        if link.status == "ACTIVE":
            link.status = "EXTENDED"
        link.version += 1
        link.save(update_fields=["expected_return_at", "status", "version", "updated_at"])
        extension.status = "APPLIED"
        extension.applied_at = timezone.now()
        extension.save(update_fields=["status", "applied_at"])
        return link

    # ------------------------------------------------------------------
    # 到期/超期检测
    # ------------------------------------------------------------------
    def due_soon(self, days: int = 30, as_of: Optional[date] = None) -> list:
        as_of = as_of or timezone.localdate()
        horizon = as_of + timedelta(days=days)
        return list(
            HrTemporaryAssignmentLink.objects.filter(
                tenant_id=self.tenant_id,
                status__in=("ACTIVE", "EXTENDED"),
                expected_return_at__lte=horizon,
                expected_return_at__gt=as_of,
            ).select_related("change_case_id", "source_assignment_id", "temporary_assignment_id")
        )

    def overdue(self, as_of: Optional[date] = None) -> list:
        as_of = as_of or timezone.localdate()
        return list(
            HrTemporaryAssignmentLink.objects.filter(
                tenant_id=self.tenant_id,
                status__in=("ACTIVE", "EXTENDED"),
                expected_return_at__lt=as_of,
            ).select_related("change_case_id", "source_assignment_id", "temporary_assignment_id")
        )

    def active(self) -> list:
        return list(
            HrTemporaryAssignmentLink.objects.filter(
                tenant_id=self.tenant_id,
                status__in=("ACTIVE", "EXTENDED"),
            ).select_related("change_case_id", "source_assignment_id", "temporary_assignment_id")
        )
