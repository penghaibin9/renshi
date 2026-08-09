"""
hr_staff/services/common.py —— 公共写路径辅助（P1-6 跨租户防线）。

resolve_staff：把 UUID/str/实例 解析为 HrStaffMaster，并强制 tenant 一致性；
违反 → CROSS_TENANT_REFERENCE。所有跨租户写路径必须经此解析目标实体。
"""

from __future__ import annotations

from typing import Optional

from hr_staff.models import HrStaffMaster


class CrossTenantReference(Exception):
    code = "CROSS_TENANT_REFERENCE"


class StaffNotFound(Exception):
    code = "STAFF_NOT_FOUND"


def resolve_staff(tenant_id: int, staff_id) -> Optional[HrStaffMaster]:
    """解析 staff（UUID/str/HrStaffMaster）并校验 tenant。"""
    if isinstance(staff_id, HrStaffMaster):
        if staff_id.tenant_id != tenant_id:
            raise CrossTenantReference("staff 不属于当前学校")
        return staff_id
    try:
        staff = HrStaffMaster.objects.filter(tenant_id=tenant_id, id=staff_id).first()
    except (ValueError, TypeError):
        return None
    if staff is None:
        raise StaffNotFound("STAFF_NOT_FOUND")
    return staff
