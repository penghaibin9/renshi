"""
hr_staff/legacy/projection_service.py —— Authority → Horilla Employee 单向投影（总册 §32.4，S11）。

原则：
- 单向 authority → legacy；projection failure 可重试；
- 有 reconciliation（HrLegacyProjectionState）；
- 不允许 legacy edit 反向覆盖 authority；
- 投影只写兼容字段（当前姓名/联系/组织/岗位/类型投影），不写历史。
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction

from hr_staff.models import HrLegacyProjectionState
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService


def _legacy_employee_model():
    from employee.models import Employee

    return Employee


class LegacyProjectionError(Exception):
    code = "LEGACY_PROJECTION_FAILED"


class LegacyEmployeeProjectionService:
    """authority → Horilla Employee 当前投影（S11）。"""

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    @transaction.atomic
    def project_staff(self, staff) -> dict:
        """
        将 HrStaffMaster 当前事实投影到 Horilla Employee/EmployeeWorkInformation。
        返回投影结果（updated / skipped / failed）。
        """
        from hr_staff.models import HrStaffMaster

        if not isinstance(staff, HrStaffMaster):
            staff = HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=staff).first()
        if staff is None:
            raise LegacyProjectionError("STAFF_NOT_FOUND")

        try:
            legacy_emp = self._get_legacy_employee(staff.legacy_employee_id)
            if legacy_emp is None:
                return {"status": "skipped", "reason": "NO_LEGACY_LINK"}
            self._project_person(staff, legacy_emp)
            self._project_work_info(staff, legacy_emp)
            self._record_projection_state(staff, legacy_emp)
            return {"status": "updated", "legacyEmployeeId": legacy_emp.id}
        except Exception as exc:
            raise LegacyProjectionError(f"{exc}")

    def _get_legacy_employee(self, legacy_employee_id):
        if not legacy_employee_id:
            return None
        # “没有映射”与“旧表查询失败”必须区分。后者由 project_staff 转成
        # LEGACY_PROJECTION_FAILED 进入重试/告警，不能伪装成 NO_LEGACY_LINK。
        return _legacy_employee_model().objects.filter(id=legacy_employee_id).first()

    def _project_person(self, staff, legacy_emp):
        """姓名/性别等 Person 层投影（单向，不碰 email 唯一身份）。"""
        person = staff.person_id
        update_fields = []
        if person.legal_name:
            legacy_emp.employee_first_name = person.legal_name
            update_fields.append("employee_first_name")
        if person.gender_code:
            legacy_emp.gender = {
                "M": "male",
                "F": "female",
                "O": "other",
                "U": None,
            }.get(person.gender_code) or legacy_emp.gender
            update_fields.append("gender")
        if person.birth_date and not legacy_emp.dob:
            legacy_emp.dob = person.birth_date
            update_fields.append("dob")
        if update_fields:
            legacy_emp.save(update_fields=update_fields)

    def _project_work_info(self, staff, legacy_emp):
        """当前组织/岗位/类型投影（legacy 兼容字段）。"""
        qs = EffectiveDatedQueryService(self.tenant_id)
        primary = qs.primary_assignment_as_of(staff.id)
        work_info = getattr(legacy_emp, "employee_work_info", None)
        if work_info is None or primary is None:
            return
        update_fields = []
        # 仅当 legacy 尚无映射时写入 legacy 映射列（不反向覆盖 authority）
        if primary.legacy_department_id and not work_info.department_id:
            from base.models import Department

            dept = Department.objects.filter(id=primary.legacy_department_id).first()
            if dept:
                work_info.department_id = dept
                update_fields.append("department_id")
        if primary.legacy_job_position_id and not work_info.job_position_id:
            from base.models import JobPosition

            pos = JobPosition.objects.filter(id=primary.legacy_job_position_id).first()
            if pos:
                work_info.job_position_id = pos
                update_fields.append("job_position_id")
        if primary.effective_from and not work_info.date_joining:
            work_info.date_joining = primary.effective_from
            update_fields.append("date_joining")
        if update_fields:
            work_info.save(update_fields=update_fields)

    def _record_projection_state(self, staff, legacy_emp):
        state, _ = HrLegacyProjectionState.objects.update_or_create(
            tenant_id=self.tenant_id,
            legacy_employee_id=legacy_emp.id,
            defaults={
                "staff_id": staff,
                "last_projected_at": None,
            },
        )
        from django.utils import timezone

        state.last_projected_at = timezone.now()
        state.save(update_fields=["last_projected_at"])
