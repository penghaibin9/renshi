"""
hr_changes/jobs/reconcile_projection.py —— 双读对账（S10，总册 §58）。

HR03 当前事实 ↔ legacy EmployeeWorkInformation 投影核对：
- 不一致 → HR06_PROJECTION_DRIFT（记录 DataQualityFinding，不静默修复权威数据）。
权威源：HR03（HrStaffAssignment 当前主岗 / HrEmploymentRelationship / HrStaffMaster）。
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from hr_staff.models import HrStaffMaster
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


def reconcile_staff_projection(
    staff: HrStaffMaster,
    *,
    as_of: date | None = None,
) -> dict:
    """对账单个 staff；返回 {matched, drifts: [...]}。"""
    from employee.models import EmployeeWorkInformation

    as_of = as_of or timezone.localdate()
    qs = EffectiveDatedQueryService(staff.tenant_id)
    primary = qs.primary_assignment_as_of(staff.id, as_of)

    if not staff.legacy_employee_id:
        return {"matched": True, "drifts": []}  # 未映射 legacy，跳过

    work_info = EmployeeWorkInformation.objects.filter(
        employee_id=staff.legacy_employee_id
    ).first()
    if work_info is None:
        return {
            "matched": False,
            "drifts": [{"field": "work_info", "code": "HR06_PROJECTION_DRIFT", "message": "缺少 legacy WorkInformation"}],
        }

    drifts = []

    # 组织
    expected_org = primary.organization_id.stable_code if primary and primary.organization_id else ""
    actual_org = (
        work_info.department_id.department if work_info.department_id else ""
    )
    if expected_org and actual_org != expected_org:
        drifts.append(
            {
                "field": "department",
                "code": "HR06_PROJECTION_DRIFT",
                "expected": expected_org,
                "actual": actual_org,
            }
        )

    # 岗位
    expected_pos = primary.position_id.position_code if primary and primary.position_id else ""
    actual_pos = (
        work_info.job_position_id.job_position if work_info.job_position_id else ""
    )
    if expected_pos and actual_pos != expected_pos:
        drifts.append(
            {
                "field": "job_position",
                "code": "HR06_PROJECTION_DRIFT",
                "expected": expected_pos,
                "actual": actual_pos,
            }
        )

    return {"matched": len(drifts) == 0, "drifts": drifts}


def run_reconcile(*, tenant_id: int, only_drift: bool = True) -> dict:
    """全校对账；返回 {checked, drifted, staffDrifts}。"""
    if not tenant_id:
        raise ValueError("tenant_id is required for HR06 reconciliation")
    staffs = HrStaffMaster.objects.filter(tenant_id=tenant_id).select_related("person_id")

    checked = 0
    drifted = 0
    staff_drifts = []
    for staff in staffs.iterator(chunk_size=500):
        result = reconcile_staff_projection(staff)
        checked += 1
        if not result["matched"]:
            drifted += 1
            if not only_drift:
                staff_drifts.append(
                    {
                        "staffNo": staff.staff_no,
                        "staffName": staff.person_id.legal_name,
                        "drifts": result["drifts"],
                    }
                )
    return {"checked": checked, "drifted": drifted, "staffDrifts": staff_drifts}
