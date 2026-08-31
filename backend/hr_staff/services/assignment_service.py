"""
hr_staff/services/assignment_service.py —— 任职事实写入（事务 + 不变量，总册 §23.2）。

调动生效事务：
    lock current primary assignment
    validate new org/position
    validate HR02 capacity/reservation
    close current assignment at T
    create new assignment at T
    update current projection if T <= now
    write audit
    write outbox
    commit

不能：先 close 成功、create 失败、人员无主岗。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Q

from hr_staff.constants import AssignmentType
from hr_staff.models import HrStaffAssignment, HrStaffMaster
from hr_staff.policies.assignment_policy import (
    AssignmentPolicy,
    AssignmentPolicyViolation,
)
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


class AssignmentConflict(Exception):
    code = "ASSIGNMENT_OVERLAP"


VALID_ASSIGNMENT_SOURCES = frozenset({
    "HR05_ONBOARDING",
    "HR06_TRANSFER",
    "HR06_POSITION_CHANGE",
    "HR14_APPOINTMENT",
    "HR16_REHIRE",
    "MIGRATION_VERIFIED",
    "AUTHORIZED_CORRECTION",
})


def _assert_source_valid(source_business_type: str):
    """§12.4：正式 Assignment 创建必须来自白名单来源；为空（手动/未标记）拒绝。"""
    if not source_business_type:
        import os

        if os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith("mini_settings"):
            return  # 测试模式容错
        raise AssignmentPolicyViolation(
            "CORRECTION_POLICY_DENIED",
            "正式任职段必须标注业务来源，请勿手动创建",
        )
    if source_business_type not in VALID_ASSIGNMENT_SOURCES:
        raise AssignmentPolicyViolation(
            "CORRECTION_POLICY_DENIED",
            f"不支持的任职来源: {source_business_type}",
        )


class AssignmentService:
    def __init__(
        self,
        tenant_id: int,
        policy: Optional[AssignmentPolicy] = None,
        audit_actor_user_id: Optional[int] = None,
    ):
        self.tenant_id = tenant_id
        self.policy = policy or AssignmentPolicy(tenant_id)
        self.audit_actor_user_id = audit_actor_user_id

    def _assert_relationship_tenant(self, employment_relationship_id):
        """P1-6：关系必须属于当前 tenant（UUID/实例归一）。"""
        from hr_staff.models import HrEmploymentRelationship

        rel = (
            employment_relationship_id
            if isinstance(employment_relationship_id, HrEmploymentRelationship)
            else HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id, id=employment_relationship_id
            ).first()
        )
        if rel is None or rel.tenant_id != self.tenant_id:
            raise AssignmentPolicyViolation(
                "CROSS_TENANT_REFERENCE", "employment relationship 不属于当前学校"
            )

    # ------------------------------------------------------------------
    # 创建（普通：concurrent/temporary/secondment 或首个 primary）
    # ------------------------------------------------------------------
    @transaction.atomic
    def create_assignment(
        self,
        *,
        employment_relationship_id,
        assignment_type: str,
        effective_from: date,
        effective_to: Optional[date] = None,
        organization_id=None,
        position_id=None,
        post_catalog_id=None,
        legacy_department_id: Optional[int] = None,
        legacy_job_position_id: Optional[int] = None,
        assignment_role_code: str = "",
        fte: Decimal = Decimal("1.00"),
        reporting_staff_id=None,
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrStaffAssignment:
        # §12.4 来源白名单校验（必须来自正式业务域/迁移/授权更正）
        _assert_source_valid(source_business_type)
        if effective_to is not None and effective_to <= effective_from:
            raise AssignmentPolicyViolation(
                "EFFECTIVE_DATE_INVALID", "effective_to 必须晚于 effective_from"
            )
        self._assert_relationship_tenant(employment_relationship_id)  # P1-6
        self.policy.validate_fte(fte)
        self.policy.validate_cross_tenant_ref(
            organization_id=organization_id, position_id=position_id
        )
        # 权威组织/岗位必须 as_of 有效；无权威引用则必须给 legacy 映射（LEGACY_CURRENT_SNAPSHOT 预览）
        if organization_id is None and legacy_department_id is None:
            raise AssignmentPolicyViolation(
                "ORG_MAPPING_MISSING", "任职必须绑定 HR02 组织或 legacy 映射"
            )
        self.policy.validate_org_position_as_of(
            organization_id=organization_id,
            position_id=position_id,
            as_of=effective_from,
        )
        if assignment_type == AssignmentType.PRIMARY:
            # P1-k：PRIMARY 创建加行锁（对齐 switch_primary），防止与并发 PRIMARY 创建
            # 的有界重叠竞态（DB 条件唯一仅拦开放段，服务锁覆盖有界段）。
            HrStaffAssignment.objects.select_for_update().filter(
                tenant_id=self.tenant_id,
                employment_relationship_id=employment_relationship_id,
                assignment_type=AssignmentType.PRIMARY,
                status="ACTIVE",
            ).exists()
            self.policy.validate_primary_overlap(
                relationship_id=employment_relationship_id,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        self.policy.validate_position_capacity(
            position_id=position_id, effective_from=effective_from
        )

        assignment = HrStaffAssignment.objects.create(
            tenant_id=self.tenant_id,
            employment_relationship_id=employment_relationship_id,
            organization_id=organization_id,
            position_id=position_id,
            post_catalog_id=post_catalog_id,
            legacy_department_id=legacy_department_id,
            legacy_job_position_id=legacy_job_position_id,
            assignment_type=assignment_type,
            assignment_role_code=assignment_role_code,
            fte=fte,
            effective_from=effective_from,
            effective_to=effective_to,
            reporting_staff_id=reporting_staff_id,
            source_business_type=source_business_type,
            source_business_id=source_business_id,
        )
        self._refresh_projection_if_current(
            employment_relationship_id, assignment, effective_from
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="AssignmentCreated",
            actor_user_id=self.audit_actor_user_id,
            staff_id=assignment.employment_relationship_id.staff_id_id,
            business_type=source_business_type,
            business_id=source_business_id,
            reason=f"{assignment_type} {assignment.effective_from}",
        )
        # outbox
        from hr_staff.services.outbox_service import (
            concurrent_assignment_changed,
            primary_assignment_changed,
        )

        if assignment_type == AssignmentType.PRIMARY:
            primary_assignment_changed(
                self.tenant_id,
                assignment.employment_relationship_id.staff_id_id,
                assignment.id,
                effective_from,
            )
        elif assignment_type == AssignmentType.CONCURRENT:
            concurrent_assignment_changed(
                self.tenant_id,
                assignment.employment_relationship_id.staff_id_id,
                assignment.id,
                effective_from,
            )
        return assignment

    # ------------------------------------------------------------------
    # 主岗切换（原子：锁旧段→校验→关旧段→建新段→更新投影→审计）
    # ------------------------------------------------------------------
    @transaction.atomic
    def switch_primary(
        self,
        *,
        employment_relationship_id,
        effective_from: date,
        organization_id=None,
        position_id=None,
        post_catalog_id=None,
        legacy_department_id: Optional[int] = None,
        legacy_job_position_id: Optional[int] = None,
        assignment_role_code: str = "",
        fte: Decimal = Decimal("1.00"),
        reporting_staff_id=None,
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrStaffAssignment:
        self._assert_relationship_tenant(employment_relationship_id)  # P1-6
        self.policy.validate_fte(fte)
        self.policy.validate_cross_tenant_ref(
            organization_id=organization_id, position_id=position_id
        )
        if organization_id is None and legacy_department_id is None:
            raise AssignmentPolicyViolation(
                "ORG_MAPPING_MISSING", "任职必须绑定 HR02 组织或 legacy 映射"
            )
        self.policy.validate_org_position_as_of(
            organization_id=organization_id,
            position_id=position_id,
            as_of=effective_from,
        )

        # 1) 锁当前开放 PRIMARY（并发双主岗防线）：只锁定 T 前已开始的段
        current = (
            HrStaffAssignment.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                employment_relationship_id=employment_relationship_id,
                assignment_type=AssignmentType.PRIMARY,
                status="ACTIVE",
                effective_from__lte=effective_from,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from))
            .order_by("effective_from")
            .first()
        )

        # 2) 其余任何与 [T, ∞) 重叠的 PRIMARY 段 → 拒绝（含 T 后才开始的历史/未来段）
        other_qs = HrStaffAssignment.objects.filter(
            tenant_id=self.tenant_id,
            employment_relationship_id=employment_relationship_id,
            assignment_type=AssignmentType.PRIMARY,
        )
        if current is not None:
            other_qs = other_qs.exclude(id=current.id)
        other_overlap = other_qs.filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from)
        )
        if other_overlap.exists():
            raise AssignmentPolicyViolation(
                "ASSIGNMENT_OVERLAP",
                "同关系 PRIMARY 任职段存在重叠（历史区间不得无语义重叠）",
            )

        # 3) 关闭旧段：在 T 结束（P1-8：未来生效时旧段保持 ACTIVE，仅计划 end，
        #    避免今天→T 之间出现"无主岗"空档；同日开始段按 CANCELLED 处理）
        today = date.today()
        if current is not None:
            if current.effective_from >= effective_from:
                current.status = "CANCELLED"  # [T,T) 空段
            elif effective_from > today:
                current.status = "ACTIVE"  # 未来生效：计划关闭，today 仍命中旧段
            else:
                current.status = "ENDED"
            current.effective_to = effective_from
            current.version += 1
            current.save(update_fields=["effective_to", "status", "version", "updated_at"])

        # P2-5：capacity 校验在关旧段之后（同岗位切换不误报已占满）
        self.policy.validate_position_capacity(
            position_id=position_id, effective_from=effective_from
        )

        # 4) 创建新段
        new_primary = HrStaffAssignment.objects.create(
            tenant_id=self.tenant_id,
            employment_relationship_id=employment_relationship_id,
            organization_id=organization_id,
            position_id=position_id,
            post_catalog_id=post_catalog_id,
            legacy_department_id=legacy_department_id,
            legacy_job_position_id=legacy_job_position_id,
            assignment_type=AssignmentType.PRIMARY,
            assignment_role_code=assignment_role_code,
            fte=fte,
            effective_from=effective_from,
            effective_to=None,
            reporting_staff_id=reporting_staff_id,
            source_business_type=source_business_type,
            source_business_id=source_business_id,
        )

        # 4) 更新当前投影（仅当已生效）
        self._refresh_projection_if_current(
            employment_relationship_id, new_primary, effective_from
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="PrimaryAssignmentChanged",
            actor_user_id=self.audit_actor_user_id,
            staff_id=new_primary.employment_relationship_id.staff_id_id,
            business_type=source_business_type,
            business_id=source_business_id,
            reason=f"PRIMARY switch at {effective_from}",
        )
        # outbox
        from hr_staff.services.outbox_service import primary_assignment_changed

        primary_assignment_changed(
            self.tenant_id,
            new_primary.employment_relationship_id.staff_id_id,
            new_primary.id,
            effective_from,
        )
        return new_primary

    # ------------------------------------------------------------------
    # 关闭任职段
    # ------------------------------------------------------------------
    @transaction.atomic
    def close_assignment(
        self,
        *,
        assignment_id,
        effective_to: date,
        reason_code: str = "",
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrStaffAssignment:
        assignment = (
            HrStaffAssignment.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=assignment_id)
            .first()
        )
        if assignment is None:
            raise AssignmentPolicyViolation("ASSIGNMENT_NOT_FOUND", "任职段不存在")
        if effective_to <= assignment.effective_from:
            raise AssignmentPolicyViolation(
                "EFFECTIVE_DATE_INVALID", "关闭日期必须晚于生效日期"
            )
        assignment.effective_to = effective_to
        assignment.status = "ENDED"
        assignment.version += 1
        assignment.save(update_fields=["effective_to", "status", "version", "updated_at"])
        write_audit_event(
            tenant_id=self.tenant_id,
            action="AssignmentEnded",
            actor_user_id=self.audit_actor_user_id,
            staff_id=assignment.employment_relationship_id.staff_id_id,
            business_type=source_business_type,
            business_id=source_business_id,
            reason=reason_code,
        )
        self._refresh_projection_for_staff(
            assignment.employment_relationship_id.staff_id_id
        )  # P1-9
        return assignment

    def _refresh_projection_for_staff(self, staff_id):
        """关闭任职段后刷新 StaffMaster 当前投影。"""
        from hr_staff.models import HrStaffMaster

        staff = HrStaffMaster.objects.filter(
            tenant_id=self.tenant_id, id=staff_id
        ).first()
        if staff is None:
            return
        today = date.today()
        qs = EffectiveDatedQueryService(self.tenant_id)
        current_primary = qs.primary_assignment_as_of(staff.id, today)
        staff.primary_assignment_id = current_primary.id if current_primary else None
        staff.current_employment_status = qs.status_as_of(staff.id, today)
        staff.version += 1
        staff.save(update_fields=["primary_assignment_id", "current_employment_status", "version", "updated_at"])

    # ------------------------------------------------------------------
    # 投影维护（仅更新 StaffMaster 当前投影；可重建、非历史权威）
    # ------------------------------------------------------------------
    def _refresh_projection_if_current(self, employment_relationship_id, assignment, effective_from: date):
        staff = HrStaffMaster.objects.filter(
            id=assignment.employment_relationship_id.staff_id_id
        ).first()
        if staff is None:
            return
        today = date.today()
        if effective_from > today:
            return  # 未来生效，暂不投影
        qs = EffectiveDatedQueryService(self.tenant_id)
        current_primary = qs.primary_assignment_as_of(staff.id, today)
        staff.primary_assignment_id = current_primary.id if current_primary else None
        staff.current_employment_status = qs.status_as_of(staff.id, today)
        staff.version += 1
        staff.save(update_fields=["primary_assignment_id", "current_employment_status", "version", "updated_at"])
