"""
hr_qualification/services/legacy_projection.py —— Legacy Projection 服务（总册 §138/§170）。

- Employee.qualification → HR09 当前资格摘要（只读投影）
- 旧写入口封堵：qualification 字段修改重定向到 HR09 API
"""

from __future__ import annotations

from django.apps import apps


class LegacyQualificationProjection:
    """
    将 HR09 Authority 资格事实投影到 Horilla Employee.qualification 字段。

    总册 §170：
    - READONLY_PROJECTION：只投影 HR09 摘要，禁止反向写
    - 旧写入口封堵：拦截 Employee.qualification 的直接修改
    """

    @staticmethod
    def is_module_available() -> bool:
        return apps.is_installed("hr_qualification") and apps.is_installed("employee")

    @staticmethod
    def project_to_employee(employee_id: int, tenant_id: int) -> str:
        """
        为指定 Employee 生成当前资格摘要字符串。

        格式："教师资格:高校教师资格✓; 双师型:中级(有效)"
        若无 HR09 数据返回空字符串（不是"无"或"未认定"）。
        """
        try:
            from hr_qualification.models import (
                HrDoubleTeacherRecognition,
                HrPersonCredential,
            )
            from employee.models import Employee

            emp = Employee.objects.get(id=employee_id)
            person_id = getattr(emp, '_hr03_person_id', None)
            staff_id = getattr(emp, '_hr03_staff_master_id', None)

            parts: list[str] = []

            # 当前有效的教师资格
            teacher_creds = HrPersonCredential.objects.filter(
                tenant_id=tenant_id,
                staff_master_id=staff_id,
                catalog_item_id__category="TEACHER_QUALIFICATION",
                status="ACTIVE",
            ) if staff_id else []

            if teacher_creds.exists():
                names = ", ".join(c.credential_name_snapshot for c in teacher_creds[:3])
                verified = all(
                    c.current_verification_status == "VERIFIED" for c in teacher_creds
                )
                parts.append(f"教师资格:{names}{'✓已核验' if verified else ''}")

            # 当前有效的双师型认定
            recognition = (
                HrDoubleTeacherRecognition.objects.filter(
                    tenant_id=tenant_id,
                    staff_master_id=staff_id,
                    status="ACTIVE",
                ).first()
                if staff_id else None
            )

            if recognition:
                level_map = {
                    "DOUBLE_TEACHER_JUNIOR": "初级",
                    "DOUBLE_TEACHER_INTERMEDIATE": "中级",
                    "DOUBLE_TEACHER_SENIOR": "高级",
                }
                level_name = level_map.get(recognition.level, recognition.level)
                parts.append(f"双师型:{level_name}(有效)")

            return "; ".join(parts) if parts else ""

        except Exception:
            return ""

    @staticmethod
    def bulk_rebuild(tenant_id: int) -> dict[str, int]:
        """批量重建所有 Employee 的 qualification 投影字段。"""
        try:
            from employee.models import Employee
            from employee.models import EmployeeWorkInformation

            updated = 0
            skipped = 0
            failed = 0

            qs = Employee.objects.filter(
                employee_work_info__company_id=tenant_id, is_active=True
            )

            for emp in qs:
                try:
                    new_val = LegacyQualificationProjection.project_to_employee(
                        emp.id, tenant_id
                    )
                    if emp.qualification != new_val:
                        emp.qualification = new_val or ""
                        emp.save(update_fields=["qualification"])
                        updated += 1
                    else:
                        skipped += 1
                except Exception:
                    failed += 1

            return {"updated": updated, "skipped": skipped, "failed": failed}
        except Exception as e:
            return {"updated": 0, "skipped": 0, "failed": 0, "error": str(e)}
