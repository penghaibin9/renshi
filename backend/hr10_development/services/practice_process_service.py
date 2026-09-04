"""
hr10_development/services/practice_process_service.py

实践过程服务（总册 §87-95/§103-110）。

Activity 记录 / 证据提交 / 完成预检 / suspend-resume / transfer。
"""

from datetime import datetime, timezone

from django.db import transaction

from hr10_development.constants import (
    AssignmentStatus,
    ScheduleConflictResult,
)


class PracticeProcessService:
    """企业实践过程管理。"""

    @staticmethod
    def _lock_assignment(assignment):
        return type(assignment).objects.select_for_update().get(
            pk=assignment.pk,
            tenant_id=assignment.tenant_id,
        )

    @staticmethod
    @transaction.atomic
    def start_assignment(assignment) -> dict:
        """开始实践——前置条件检查通过才能 START。"""
        from hr10_development.services.practice_prerequisite_service import PracticePrerequisiteService

        assignment = PracticeProcessService._lock_assignment(assignment)

        plan = getattr(assignment, "practice_plan", None)
        if plan and not PracticePrerequisiteService.is_ready_to_start(plan):
            return {"status": "PREREQUISITE_MISSING"}

        if assignment.assignment_status == AssignmentStatus.IN_PROGRESS:
            return {"status": "PRACTICE_ALREADY_STARTED"}
        if assignment.assignment_status != AssignmentStatus.APPROVED:
            return {"status": "PRACTICE_STATE_CONFLICT"}

        assignment.assignment_status = AssignmentStatus.IN_PROGRESS
        assignment.started_at = datetime.now(timezone.utc)
        assignment.save(update_fields=["assignment_status", "started_at", "updated_at"])
        return {"status": "STARTED"}

    @staticmethod
    @transaction.atomic
    def suspend_assignment(assignment, reason: str, responsible_party: str) -> dict:
        """暂停实践。"""
        assignment = PracticeProcessService._lock_assignment(assignment)
        if assignment.assignment_status != AssignmentStatus.IN_PROGRESS:
            return {"status": "PRACTICE_STATE_CONFLICT"}
        if not str(reason or "").strip():
            return {"status": "SUSPEND_REASON_REQUIRED"}
        assignment.assignment_status = AssignmentStatus.SUSPENDED
        assignment.save(update_fields=["assignment_status", "updated_at"])
        return {"status": "SUSPENDED", "reason": reason, "responsibleParty": responsible_party}

    @staticmethod
    @transaction.atomic
    def resume_assignment(assignment) -> dict:
        """恢复实践。"""
        assignment = PracticeProcessService._lock_assignment(assignment)
        if assignment.assignment_status != AssignmentStatus.SUSPENDED:
            return {"status": "PRACTICE_STATE_CONFLICT"}
        assignment.assignment_status = AssignmentStatus.IN_PROGRESS
        assignment.save(update_fields=["assignment_status", "updated_at"])
        return {"status": "RESUMED"}

    @staticmethod
    def completion_precheck(assignment) -> dict:
        """
        完成前预检（总册 §103）。

        Returns: {"status": "PASS"/"FAIL"/"MISSING"/"MANUAL_REVIEW", "checks": [...]}
        """
        from hr10_development.services.duration_service import DurationService

        checks = []

        # 1. 有效时长
        duration = DurationService.calculate_assignment_duration(assignment.id, assignment.tenant_id)
        if duration["eligible_days"] <= 0:
            checks.append({"check": "required_duration", "status": "MISSING"})
        else:
            checks.append({"check": "required_duration", "status": "PASS", "days": duration["eligible_days"]})

        # 2. 企业导师评价
        from hr10_development.models.practice_process import HrEnterpriseMentorFeedback
        mentor_ok = HrEnterpriseMentorFeedback.objects.filter(assignment_id=assignment.id).exists()
        checks.append({"check": "enterprise_evaluation", "status": "PASS" if mentor_ok else "MISSING"})

        # 3. 学校评价
        from hr10_development.models.practice_process import HrPracticeSchoolEvaluation
        school_ok = HrPracticeSchoolEvaluation.objects.filter(assignment_id=assignment.id).exists()
        checks.append({"check": "school_evaluation", "status": "PASS" if school_ok else "MISSING"})

        # 4. 证据
        from hr10_development.models.practice_process import HrEnterprisePracticeEvidence
        evidence_ok = HrEnterprisePracticeEvidence.objects.filter(
            assignment_id=assignment.id,
            verification_status__in=[
                "SYSTEM_PROVIDER_VERIFIED", "TRAINING_PROVIDER_VERIFIED",
                "HR_VERIFIED", "DOCUMENT_VERIFIED", "MANUAL_COMMITTEE_VERIFIED",
            ],
        ).exists()
        checks.append({"check": "evidence", "status": "PASS" if evidence_ok else "MISSING"})

        # 5. 未解决风险
        from hr10_development.models.development_fact import HrDevelopmentRiskCase
        open_risk = HrDevelopmentRiskCase.objects.filter(
            assignment_id=assignment.id,
            status__in=["OPEN", "IN_PROGRESS"],
        ).exists()
        checks.append({"check": "open_incidents", "status": "FAIL" if open_risk else "PASS"})

        all_pass = all(c["status"] == "PASS" for c in checks)
        return {
            "status": "PASS" if all_pass else ("MANUAL_REVIEW" if any(c["status"] == "FAIL" for c in checks) else "MISSING"),
            "checks": checks,
        }
