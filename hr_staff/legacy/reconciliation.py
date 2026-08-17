"""
hr_staff/legacy/reconciliation.py —— DUAL_READ_COMPARE 对账（总册 §32.2，S11）。

对比维度（staff_no/current org/current position/employee type/date joining/status/work contact），
mismatch 必须进对账中心，不能静默忽略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


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

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

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

        # staff_no
        if staff.staff_no and legacy_emp.badge_id and staff.staff_no != legacy_emp.badge_id:
            item.mismatches.append(
                f"staff_no: authority={staff.staff_no} legacy={legacy_emp.badge_id}"
            )
        # date joining
        qs = EffectiveDatedQueryService(self.tenant_id)
        earliest = min(
            (r.effective_from for r in qs.relationships_as_of(staff.id)), default=None
        )
        if earliest and getattr(legacy_emp, "employee_work_info", None):
            legacy_joining = legacy_emp.employee_work_info.date_joining
            if legacy_joining and legacy_joining != earliest:
                item.mismatches.append(
                    f"date_joining: authority={earliest} legacy={legacy_joining}"
                )
        # status（is_active 只作提示，不作历史真值）
        current_status = qs.status_as_of(staff.id)
        legacy_active = bool(legacy_emp.is_active)
        if current_status == "ACTIVE" and not legacy_active:
            item.mismatches.append("status: authority=ACTIVE legacy=inactive")
        elif current_status not in ("ACTIVE", "PENDING_ENTRY") and legacy_active:
            item.mismatches.append(f"status: authority={current_status} legacy=active")
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

        from employee.models import Employee

        return Employee.objects.filter(
            id=legacy_employee_id,
            employee_work_info__company_id_id=self.tenant_id,
        ).first()
