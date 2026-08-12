"""
hr_staff/legacy/migration.py —— Wave 0 盘点 + Wave 1/2 迁移（总册 §33，S11）。

Wave 0 只盘点不写 authority；
Wave 1 Person/StaffMaster；
Wave 2 Relationship/Assignment（依赖 HR02 映射）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.db import transaction


@dataclass
class MigrationReport:
    wave: str
    counts: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)

    def summary(self) -> str:
        return f"wave={self.wave} counts={self.counts} issues={len(self.issues)}"


class MigrationService:
    """Legacy → HR03 迁移（S11）。"""

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Wave 0：只盘点（P1-10：按 tenant 过滤，不跨租户）
    # ------------------------------------------------------------------
    def wave0_inventory(self) -> MigrationReport:
        report = MigrationReport(wave="0")
        try:
            from employee.models import Employee, EmployeeWorkInformation

            employees = Employee.objects.filter(
                employee_work_info__company_id=self.tenant_id
            )
            report.counts["employee_total"] = employees.count()
            report.counts["employee_active"] = employees.filter(is_active=True).count()
            report.counts["employee_inactive"] = employees.filter(is_active=False).count()
            report.counts["badge_missing"] = employees.filter(badge_id__isnull=True).count()
            work_infos = EmployeeWorkInformation.objects.filter(company_id=self.tenant_id)
            report.counts["work_info_total"] = work_infos.count()
            report.counts["work_info_no_company"] = work_infos.filter(
                company_id__isnull=True
            ).count()
            report.counts["work_info_no_date_joining"] = work_infos.filter(
                date_joining__isnull=True
            ).count()
        except Exception as exc:
            report.issues.append(f"LEGACY_READ_FAILED: {exc}")
        return report

    # ------------------------------------------------------------------
    # Wave 1：Person + StaffMaster 骨架（不切读取）
    # ------------------------------------------------------------------
    @transaction.atomic
    def wave1_person_staff(
        self,
        *,
        employee,
        legal_name: Optional[str] = None,
        document_number: Optional[str] = None,
        source: str = "MIGRATED",
    ) -> dict:
        from hr_staff.services.person_identity_service import (
            PersonDuplicateHardMatch,
            PersonDuplicateReviewRequired,
            PersonIdentityService,
        )
        from hr_staff.services.staff_master_service import (
            DuplicateStaffMaster,
            StaffMasterService,
        )

        person_svc = PersonIdentityService()
        staff_svc = StaffMasterService()
        name = legal_name or employee.employee_first_name
        try:
            person = person_svc.create_person_with_identity(
                tenant_id=self.tenant_id,
                legal_name=name,
                birth_date=employee.dob,
                gender_code={"male": "M", "female": "F", "other": "O"}.get(employee.gender),
                document_number=document_number,
            )
        except PersonDuplicateReviewRequired:
            return {
                "status": "review_required",
                "reason": "LIKELY_MATCH",
                "legacyEmployeeId": employee.id,
            }
        except PersonDuplicateHardMatch:
            # N5：同证件异名 → 人工去重裁决，不中断整批
            return {
                "status": "review_required",
                "reason": "HARD_MATCH_NAME_CONFLICT",
                "legacyEmployeeId": employee.id,
            }
        try:
            staff = staff_svc.create_staff(
                tenant_id=self.tenant_id,
                person_id=person,
                staff_no=employee.badge_id or None,
                legacy_employee_id=employee.id,
                source=source,
            )
        except DuplicateStaffMaster:
            staff = staff_svc.get_by_legacy_employee(self.tenant_id, employee.id)
            if staff is None:
                return {"status": "skipped", "reason": "DUPLICATE_STAFF_NO_RELINK", "legacyEmployeeId": employee.id}
        return {"status": "created", "staffId": str(staff.id), "legacyEmployeeId": employee.id}

    # ------------------------------------------------------------------
    # Wave 2：Relationship + Assignment
    # ------------------------------------------------------------------
    @transaction.atomic
    def wave2_employment(self, *, staff, legacy_work_info=None, legacy_department_id=None) -> dict:
        from hr_staff.services.assignment_service import AssignmentService
        from hr_staff.services.employment_service import EmploymentService

        joining = (legacy_work_info or {}).get("date_joining") or date.today()
        emp_svc = EmploymentService(self.tenant_id)
        assign_svc = AssignmentService(self.tenant_id)
        source_business_id = f"legacy-employee-{staff.legacy_employee_id}"
        try:
            rel = emp_svc.start_relationship(
                staff_id=staff,
                relationship_type="REGULAR_EMPLOYMENT",
                effective_from=joining,
                source_business_type="MIGRATION_VERIFIED",
                source_business_id=source_business_id,
            )
            assign_svc.create_assignment(
                employment_relationship_id=rel,
                assignment_type="PRIMARY",
                effective_from=joining,
                organization_id=None,
                legacy_department_id=legacy_department_id,
                source_business_type="MIGRATION_VERIFIED",
                source_business_id=source_business_id,
            )
            return {"status": "created", "relationshipId": str(rel.id)}
        except Exception as exc:
            return {"status": "failed", "reason": f"{exc}"}

    # ------------------------------------------------------------------
    # 幂等执行（整批：先 Wave0，再 Wave1，再 Wave2）
    # ------------------------------------------------------------------
    def run_wave(self, wave: str) -> MigrationReport:
        report = MigrationReport(wave=wave)
        if wave == "0":
            return self.wave0_inventory()
        if wave in ("1", "2"):
            from employee.models import Employee

            employees = Employee.objects.filter(
                employee_work_info__company_id=self.tenant_id
            ).order_by("id")
            created = skipped = review = failed = 0
            for employee in employees:
                if wave == "1":
                    result = self.wave1_person_staff(employee=employee)
                else:
                    from hr_staff.models import HrStaffMaster

                    staff = HrStaffMaster.objects.filter(
                        tenant_id=self.tenant_id, legacy_employee_id=employee.id
                    ).first()
                    if staff is None:
                        skipped += 1
                        continue
                    work = getattr(employee, "employee_work_info", None)
                    result = self.wave2_employment(
                        staff=staff,
                        legacy_work_info=(
                            {
                                "date_joining": work.date_joining,
                            }
                            if work
                            else None
                        ),
                        legacy_department_id=work.department_id_id if work and work.department_id else None,
                    )
                status = result.get("status")
                if status == "created":
                    created += 1
                elif status == "review_required":
                    review += 1
                elif status == "failed":
                    failed += 1
                    report.issues.append(f"employee={employee.id} {result}")
                else:
                    skipped += 1
            report.counts = {
                "created": created,
                "skipped": skipped,
                "review_required": review,
                "failed": failed,
            }
        return report
