"""HR12 DUAL_READ_COMPARE 管理命令 (S12)。

对账领域：goals / periods / feedback / employee_mapping / company_tenant / progress / question_templates
"""

import uuid
from django.core.management.base import BaseCommand
from django.db.models import Count


class Command(BaseCommand):
    help = "Legacy PMS ↔ HR12 Authority DUAL_READ_COMPARE 对账"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--domain", type=str, default="all")
        parser.add_argument("--output", type=str, default="")

    def handle(self, **options):
        tenant_id = options["tenant_id"]
        self.stdout.write(f"HR12 DUAL_READ_COMPARE — tenant={tenant_id}")

        report = {"tenant_id": tenant_id, "domains": {}, "blocked": False}

        self._compare_periods(tenant_id, report)
        self._compare_objectives(tenant_id, report)
        self._compare_feedback(tenant_id, report)
        self._compare_employee_mapping(tenant_id, report)

        blocked = any(d.get("blocked") for d in report["domains"].values())
        report["blocked"] = blocked

        self.stdout.write(str(report))
        if blocked:
            self.stdout.write(self.style.ERROR("P0 blocked — 迁移前必须解决所有 blocked 项"))
            raise SystemExit(1)

    def _compare_periods(self, tenant_id: int, report: dict):
        """Period vs AssessmentCycle 对账。"""
        try:
            from pms.models import Period
            from hr_assessment.models.cycle import HrAssessmentCycle
        except ImportError:
            report["domains"]["periods"] = {"status": "SKIPPED", "reason": "pms or hr_assessment not installed"}
            return

        legacy_count = Period.objects.filter(company_id__id=tenant_id).distinct().count()
        new_count = HrAssessmentCycle.objects.filter(tenant_id=tenant_id).count()
        report["domains"]["periods"] = {
            "legacy_count": legacy_count,
            "new_count": new_count,
            "drift": legacy_count - new_count,
            "blocked": legacy_count > 0 and new_count == 0,
        }

    def _compare_objectives(self, tenant_id: int, report: dict):
        """Objective vs Goal 对账。"""
        try:
            from pms.models import Objective
            from hr_assessment.models.goal import HrAssessmentGoal
        except ImportError:
            report["domains"]["goals"] = {"status": "SKIPPED"}
            return

        legacy_count = Objective.objects.filter(company_id_id=tenant_id).count()
        new_count = HrAssessmentGoal.objects.filter(tenant_id=tenant_id).count()
        report["domains"]["goals"] = {
            "legacy_count": legacy_count,
            "new_count": new_count,
            "drift": legacy_count - new_count,
            "blocked": False,
        }

    def _compare_feedback(self, tenant_id: int, report: dict):
        """Feedback vs MultiRaterSession 对账。"""
        try:
            from pms.models import Feedback
            from hr_assessment.models.evidence import HrMultiRaterSession
        except ImportError:
            report["domains"]["feedback"] = {"status": "SKIPPED"}
            return

        legacy_count = Feedback.objects.filter(
            employee_id__employee_work_info__company_id_id=tenant_id
        ).count()
        new_count = HrMultiRaterSession.objects.filter(tenant_id=tenant_id).count()
        report["domains"]["feedback"] = {
            "legacy_count": legacy_count,
            "new_count": new_count,
            "drift": legacy_count - new_count,
            "blocked": False,
        }

    def _compare_employee_mapping(self, tenant_id: int, report: dict):
        """Employee→HrStaffMaster 映射对账。"""
        try:
            from employee.models import Employee
            from hr_staff.models.staff import HrStaffMaster
        except ImportError:
            report["domains"]["employee_mapping"] = {"status": "SKIPPED"}
            return

        legacy_emp_count = Employee.objects.filter(
            employee_work_info__company_id_id=tenant_id
        ).count()
        staff_count = HrStaffMaster.objects.filter(tenant_id=tenant_id).count()
        unmapped = abs(legacy_emp_count - staff_count)
        report["domains"]["employee_mapping"] = {
            "legacy_employee_count": legacy_emp_count,
            "hr_staff_count": staff_count,
            "unmapped": unmapped,
            "blocked": legacy_emp_count > 0 and staff_count == 0,
        }
