"""
hr_staff/legacy/reconciliation.py —— DUAL_READ_COMPARE 对账（总册 §32.2，S11）。

对比维度（staff_no/current org/current position/employee type/date joining/status/work contact），
mismatch 必须进对账中心，不能静默忽略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.db.models import Min
from django.utils import timezone

from hr_staff.models import HrEmploymentRelationship
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


def _legacy_employee_model():
    from employee.models import Employee

    return Employee


@dataclass
class ReconciliationItem:
    legacy_employee_id: int
    staff_id: Optional[str] = None
    staff_no_match: bool = True
    mismatches: list = field(default_factory=list)

    @property
    def has_mismatch(self) -> bool:
        return bool(self.mismatches)


class ReconciliationService:
    """authority vs legacy 对账（只读）。"""

    def __init__(self, tenant_id: int, *, as_of: date | None = None):
        self.tenant_id = tenant_id
        self.as_of = as_of or timezone.localdate()

    def reconcile_staff(self, staff) -> ReconciliationItem:
        from hr_staff.models import HrStaffMaster

        if not isinstance(staff, HrStaffMaster):
            staff = HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=staff).first()
        if staff is None:
            return ReconciliationItem(legacy_employee_id=0, mismatches=["STAFF_NOT_FOUND"])
        item = ReconciliationItem(
            legacy_employee_id=staff.legacy_employee_id or 0,
            staff_id=str(staff.id),
        )
        legacy_emp = self._legacy_employee(staff.legacy_employee_id)
        if legacy_emp is None:
            item.mismatches.append("LEGACY_LINK_MISSING")
            return item

        # 对账项只返回维度代码，不回传两边的原始值，避免工号等个人信息进入日志/告警。
        if staff.staff_no and legacy_emp.badge_id and staff.staff_no != legacy_emp.badge_id:
            item.staff_no_match = False
            item.mismatches.append("STAFF_NO_MISMATCH")
        # date joining
        qs = EffectiveDatedQueryService(self.tenant_id)
        earliest = HrEmploymentRelationship.objects.filter(
            tenant_id=self.tenant_id,
            staff_id=staff.id,
        ).exclude(status__in=("DRAFT", "CANCELLED")).aggregate(
            earliest=Min("effective_from")
        )["earliest"]
        work_info = getattr(legacy_emp, "employee_work_info", None)
        if earliest and work_info:
            legacy_joining = work_info.date_joining
            if legacy_joining and legacy_joining != earliest:
                item.mismatches.append("DATE_JOINING_MISMATCH")

        # 当前主岗的 legacy 映射列与旧系统当前快照核对。权威组织/岗位尚未映射时，
        # 这两列仍是双读阶段唯一可比较的稳定键。
        primary = qs.primary_assignment_as_of(staff.id, self.as_of)
        if primary and work_info:
            legacy_department_id = getattr(work_info, "department_id_id", None)
            legacy_position_id = getattr(work_info, "job_position_id_id", None)
            if (
                primary.legacy_department_id is not None
                and primary.legacy_department_id != legacy_department_id
            ):
                item.mismatches.append("DEPARTMENT_MISMATCH")
            if (
                primary.legacy_job_position_id is not None
                and primary.legacy_job_position_id != legacy_position_id
            ):
                item.mismatches.append("POSITION_MISMATCH")

        # status（is_active 只作提示，不作历史真值）
        current_status = qs.status_as_of(staff.id, self.as_of)
        legacy_active = bool(legacy_emp.is_active)
        if current_status == "ACTIVE" and not legacy_active:
            item.mismatches.append("STATUS_MISMATCH")
        elif current_status not in ("ACTIVE", "PENDING_ENTRY") and legacy_active:
            item.mismatches.append("STATUS_MISMATCH")
        return item

    def reconcile_all(self) -> dict:
        from hr_staff.models import HrStaffMaster

        staff_list = HrStaffMaster.objects.filter(tenant_id=self.tenant_id)
        items = [self.reconcile_staff(s) for s in staff_list]
        mismatched = [i for i in items if i.has_mismatch]
        return {
            "total": len(items),
            "mismatchCount": len(mismatched),
            "mismatched": [
                {
                    "legacyEmployeeId": i.legacy_employee_id,
                    "staffId": i.staff_id,
                    "issues": i.mismatches,
                }
                for i in mismatched
            ],
        }

    def _legacy_employee(self, legacy_employee_id):
        """按 tenant 读取 legacy Employee；禁止依赖 request thread-local 和跨租户主键直取。"""
        if not legacy_employee_id:
            return None

        return _legacy_employee_model().objects.filter(
            id=legacy_employee_id,
            employee_work_info__company_id_id=self.tenant_id,
        ).first()
