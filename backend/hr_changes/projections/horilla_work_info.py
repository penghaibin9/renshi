"""
hr_changes/projections/horilla_work_info.py —— Legacy WorkInformation 投影（S9，总册 §55/§58）。

唯一合法写入路径：
    HR03 facts（HrStaffAssignment/HrEmploymentRelationship/HrStaffMaster）
      → 投影 → EmployeeWorkInformation（department/job_position/reporting_manager/employee_type/location）

禁止反向：把 Legacy current state 当权威覆盖 HR03；不 fallback。
映射解析：
- department ← 主岗 organization（按 HrLegacyObjectLink 或 stable_code ↔ legacy Department.department）；
- job_position ← 主岗 position（按 HrLegacyObjectLink 或 position_code ↔ legacy JobPosition.job_position）；
- reporting_manager ← reporting_staff（经 legacy_employee_id 映射 legacy Employee）；
- employee_type ← relationship_type（→ legacy EmployeeType 名称匹配）；
- location ← 主岗 location_code（HR02 组织版本受控地点代码）。
未映射到 legacy FK 时置空并计入未映射清单（由 S10 迁移核对）。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.utils import timezone

from hr_changes.constants import ChangeActionCode
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


class ProjectionResult(dict):
    """{updated, unmapped, legacyEmployeeId, fields}"""


def project_staff_work_info(tenant_id: int, staff_id) -> ProjectionResult:
    """按 HR03 当前事实投影 EmployeeWorkInformation（幂等，可重复执行）。"""
    from employee.models import Employee, EmployeeWorkInformation
    from hr_staff.models import HrStaffMaster

    staff = HrStaffMaster.objects.filter(tenant_id=tenant_id, id=staff_id).first()
    result = ProjectionResult(
        updated=False, unmapped=[], legacyEmployeeId=None, fields={}
    )
    if staff is None or not staff.legacy_employee_id:
        result["unmapped"].append("legacy_employee_id")
        return result

    employee = Employee.objects.filter(id=staff.legacy_employee_id).first()
    if employee is None:
        result["unmapped"].append("legacy_employee_id")
        return result
    result["legacyEmployeeId"] = employee.id

    qs = EffectiveDatedQueryService(tenant_id)
    primary = qs.primary_assignment_as_of(staff_id, timezone.localdate())
    rel = qs.relationships_as_of(staff_id, timezone.localdate()).first()

    work_info, _ = EmployeeWorkInformation.objects.get_or_create(employee_id=employee)
    changes: dict = {}
    unmapped: list[str] = []

    # organization → legacy Department
    if primary and primary.organization_id_id:
        department = _resolve_legacy_department(tenant_id, primary.organization_id)
        if department is not None:
            changes["department_id"] = department
        else:
            unmapped.append("department")
    if primary and primary.position_id_id:
        position = _resolve_legacy_position(tenant_id, primary.position_id)
        if position is not None:
            changes["job_position_id"] = position
        else:
            unmapped.append("job_position")
    if primary and primary.reporting_staff_id_id:
        manager = _resolve_legacy_employee(tenant_id, primary.reporting_staff_id_id)
        if manager is not None:
            changes["reporting_manager_id"] = manager
        else:
            unmapped.append("reporting_manager")
    if primary and primary.location_code:
        changes["location"] = primary.location_code
    if rel:
        employee_type = _resolve_legacy_employee_type(tenant_id, rel.relationship_type)
        if employee_type is not None:
            changes["employee_type_id"] = employee_type
        else:
            unmapped.append("employee_type")

    if changes:
        for field, value in changes.items():
            setattr(work_info, field, value)
        work_info.save()
        result["updated"] = True
        result["fields"] = {
            key: (getattr(value, "id", None) if hasattr(value, "id") else value)
            for key, value in changes.items()
        }
    result["unmapped"] = unmapped
    return result


# ---------------------------------------------------------------------------
# legacy 解析（V1：稳定码 ↔ legacy 名称匹配；S10 可切到 HrLegacyObjectLink）
# ---------------------------------------------------------------------------
def _resolve_legacy_department(tenant_id, org):
    """legacy Department 按 HrLegacyObjectLink 或 HrOrganization.stable_code 匹配。"""
    from base.models import Department
    from hr_structure.models import HrLegacyObjectLink

    link = HrLegacyObjectLink.objects.filter(
        tenant_id=tenant_id, domain_entity_type="ORGANIZATION", domain_entity_id=str(org.id)
    ).first()
    if link and link.legacy_pk:
        return Department.objects.filter(id=link.legacy_pk).first()
    return Department.objects.filter(department=org.stable_code).first()


def _resolve_legacy_position(tenant_id, position):
    from base.models import JobPosition
    from hr_structure.models import HrLegacyObjectLink

    link = HrLegacyObjectLink.objects.filter(
        tenant_id=tenant_id, domain_entity_type="POSITION", domain_entity_id=str(position.id)
    ).first()
    if link and link.legacy_pk:
        return JobPosition.objects.filter(id=link.legacy_pk).first()
    return JobPosition.objects.filter(job_position=position.position_code).first()


def _resolve_legacy_employee(tenant_id, reporting_staff_id):
    from employee.models import Employee
    from hr_staff.models import HrStaffMaster

    reporter = HrStaffMaster.objects.filter(
        tenant_id=tenant_id, id=reporting_staff_id
    ).first()
    if reporter and reporter.legacy_employee_id:
        return Employee.objects.filter(id=reporter.legacy_employee_id).first()
    return None


def _resolve_legacy_employee_type(tenant_id, relationship_type: str):
    """relationship_type → legacy EmployeeType 名称匹配（名称相近映射）。"""
    from base.models import EmployeeType

    name_map = {
        "REGULAR_EMPLOYMENT": "正式",
        "CONTRACT": "合同",
        "LABOR_DISPATCH": "派遣",
        "EXTERNAL_PART_TIME": "兼职",
        "SECONDMENT": "借调",
        "RETIRED_REHIRE": "返聘",
    }
    keyword = name_map.get(relationship_type, "")
    if not keyword:
        return None
    return EmployeeType.objects.filter(employee_type__icontains=keyword).first()
