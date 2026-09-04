"""HR12 Legacy PMS Migration 管理命令。

从旧的 pms.models 迁移数据到新的 HR12 权威模型。
执行步骤：Period→Cycle, Objective→Goal, EmployeeObjective→GoalAssignment,
          KeyResult→Measure, Feedback→MultiRaterSession, Answer→MultiRaterAnswer,
          QuestionTemplate→QuestionnaireVersion。
"""

import uuid
from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Legacy PMS → HR12 Assessment 数据迁移"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        tenant_id = options["tenant_id"]
        dry = options["dry_run"]

        report = {"tenant_id": tenant_id, "steps": []}
        steps = [
            ("Period → Cycle", self._migrate_periods),
            ("Objective → Goal", self._migrate_objectives),
            ("EmployeeObjective → GoalAssignment", self._migrate_employee_objectives),
            ("KeyResult → GoalMeasure", self._migrate_key_results),
            ("QuestionTemplate → QuestionnaireVersion", self._migrate_question_templates),
            ("Feedback → MultiRaterSession", self._migrate_feedback),
            ("Answer → MultiRaterAnswer", self._migrate_answers),
        ]

        failed_steps = []
        for step_name, func in steps:
            self.stdout.write(f"Migrating: {step_name}...")
            try:
                with transaction.atomic():
                    result = func(tenant_id, dry)
                report["steps"].append({"step": step_name, **result})
            except Exception as e:
                report["steps"].append({"step": step_name, "error": str(e)[:500]})
                failed_steps.append(step_name)

        self.stdout.write(str(report))
        if failed_steps:
            raise CommandError(
                "HR12 legacy migration failed and rolled back steps: "
                + ", ".join(failed_steps)
            )

    @staticmethod
    def _stable_uuid(tenant_id: int, entity: str, legacy_id) -> uuid.UUID:
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"hr12:{tenant_id}:{entity}:{legacy_id}",
        )

    @staticmethod
    def _aware_boundary(value, *, end: bool = False):
        if isinstance(value, datetime):
            return timezone.make_aware(value) if timezone.is_naive(value) else value
        boundary = time.max if end else time.min
        return timezone.make_aware(datetime.combine(value, boundary))

    @staticmethod
    def _staff_for_legacy_employee(tenant_id: int, employee_id):
        from hr_staff.models import HrStaffMaster

        if not employee_id:
            return None
        return HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            legacy_employee_id=employee_id,
        ).first()

    def _migrate_periods(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import Period
            from hr_assessment.models.cycle import HrAssessmentCycle

            migrated = 0
            for p in Period.objects.filter(company_id__id=tenant_id).distinct():
                if dry:
                    migrated += 1
                    continue
                HrAssessmentCycle.objects.get_or_create(
                    tenant_id=tenant_id,
                    cycle_no=f"LEGACY-{p.id}",
                    assessment_type="ANNUAL",
                    defaults={
                        "name": p.period_name,
                        "start_at": self._aware_boundary(p.start_date),
                        "end_at": self._aware_boundary(p.end_date, end=True),
                        "policy_version_id": self._stable_uuid(
                            tenant_id, "legacy-period-policy", p.id
                        ),
                        "lifecycle_status": "ARCHIVED",
                    },
                )
                migrated += 1
            return {"migrated": migrated}
        except ImportError:
            return {"migrated": 0, "error": "pms 模块未安装"}

    def _migrate_objectives(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import Objective
            from hr_assessment.models.goal import (
                HrAssessmentGoal,
                HrAssessmentGoalPlan,
                HrGoalVersion,
            )
            if dry:
                return {"migrated": Objective.objects.filter(company_id_id=tenant_id).count()}
            plan, _ = HrAssessmentGoalPlan.objects.get_or_create(
                tenant_id=tenant_id, name="Legacy PMS 迁移", goal_type="ANNUAL",
                defaults={"status": "ARCHIVED"},
            )
            migrated = 0
            for obj in Objective.objects.filter(company_id_id=tenant_id):
                goal, _ = HrAssessmentGoal.objects.get_or_create(
                    tenant_id=tenant_id, goal_code=f"LEGACY-OBJ-{obj.id}",
                    defaults={
                        "goal_plan": plan,
                        "source_type": "LEGACY_MIGRATION",
                        "status": "ARCHIVED",
                    },
                )
                version_id = self._stable_uuid(tenant_id, "legacy-goal-version", obj.id)
                version, _ = HrGoalVersion.objects.get_or_create(
                    id=version_id,
                    defaults={
                        "goal": goal,
                        "version_no": 1,
                        "title": obj.title,
                        "description": obj.description or "",
                        "measures_json": [],
                        "period_config_json": {
                            "duration": obj.duration,
                            "durationUnit": obj.duration_unit,
                        },
                        "status": "ARCHIVED",
                    },
                )
                if goal.current_version_id != version.id:
                    goal.current_version_id = version.id
                    goal.save(update_fields=["current_version_id", "updated_at"])
                migrated += 1
            return {"migrated": migrated}
        except ImportError:
            return {"migrated": 0, "error": "pms 模块未安装"}

    def _migrate_employee_objectives(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import EmployeeObjective
            from hr_assessment.models.goal import HrAssessmentGoal, HrGoalAssignment

            scoped = EmployeeObjective.objects.filter(
                employee_id__employee_work_info__company_id_id=tenant_id
            ).select_related("employee_id", "objective_id")
            if dry:
                return {"migrated": scoped.count(), "skipped": 0}
            migrated = 0
            skipped = 0
            for item in scoped:
                staff = self._staff_for_legacy_employee(
                    tenant_id, item.employee_id_id
                )
                goal = None
                if item.objective_id_id:
                    goal = HrAssessmentGoal.objects.filter(
                        tenant_id=tenant_id,
                        goal_code=f"LEGACY-OBJ-{item.objective_id_id}",
                    ).first()
                if staff is None or goal is None:
                    skipped += 1
                    continue
                HrGoalAssignment.objects.get_or_create(
                    tenant_id=tenant_id,
                    goal=goal,
                    staff_id=staff.id,
                    defaults={
                        "assignment_type": "INDIVIDUAL",
                        "contribution_role": "LEGACY_ASSIGNEE",
                        "effective_period_json": {
                            "startDate": item.start_date.isoformat(),
                            "endDate": item.end_date.isoformat(),
                            "legacyStatus": item.status,
                        },
                    },
                )
                migrated += 1
            return {"migrated": migrated, "skipped": skipped}
        except ImportError:
            return {"migrated": 0}

    def _migrate_key_results(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import KeyResult
            from hr_assessment.models.goal import (
                HrAssessmentGoal,
                HrGoalMeasure,
                HrGoalVersion,
            )

            scoped = KeyResult.objects.filter(company_id_id=tenant_id)
            if dry:
                return {"migrated": scoped.count(), "skipped": 0}
            migrated = 0
            skipped = 0
            for key_result in scoped:
                objectives = key_result.objective.filter(company_id_id=tenant_id)
                if not objectives.exists():
                    skipped += 1
                    continue
                for objective in objectives:
                    goal = HrAssessmentGoal.objects.filter(
                        tenant_id=tenant_id,
                        goal_code=f"LEGACY-OBJ-{objective.id}",
                    ).first()
                    version = (
                        HrGoalVersion.objects.filter(
                            goal=goal,
                            version_no=1,
                        ).first()
                        if goal is not None
                        else None
                    )
                    if version is None:
                        skipped += 1
                        continue
                    HrGoalMeasure.objects.get_or_create(
                        id=self._stable_uuid(
                            tenant_id,
                            "legacy-goal-measure",
                            f"{objective.id}:{key_result.id}",
                        ),
                        defaults={
                            "goal_version": version,
                            "measure_code": f"LEGACY-KR-{key_result.id}",
                            "measure_type": (
                                "PERCENTAGE"
                                if key_result.progress_type == "%"
                                else "NUMBER"
                            ),
                            "target": key_result.target_value or 0,
                            "unit": key_result.progress_type or "",
                            "source_provider": "LEGACY_MIGRATION",
                        },
                    )
                    migrated += 1
            return {"migrated": migrated, "skipped": skipped}
        except ImportError:
            return {"migrated": 0}

    def _migrate_feedback(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import Feedback
            from hr_assessment.models.case import HrAssessmentCase
            from hr_assessment.models.evidence import (
                HrMultiRaterSession,
                HrQuestionnaireVersion,
            )

            scoped = Feedback.objects.filter(
                employee_id__employee_work_info__company_id_id=tenant_id
            ).select_related("employee_id", "question_template_id")
            if dry:
                return {"migrated": scoped.count(), "skipped": 0}
            migrated = 0
            skipped = 0
            for feedback in scoped:
                staff = self._staff_for_legacy_employee(
                    tenant_id, feedback.employee_id_id
                )
                case = (
                    HrAssessmentCase.objects.filter(
                        tenant_id=tenant_id,
                        staff_id=staff.id,
                    )
                    .order_by("-created_at")
                    .first()
                    if staff is not None
                    else None
                )
                questionnaire = HrQuestionnaireVersion.objects.filter(
                    id=self._stable_uuid(
                        tenant_id,
                        "legacy-questionnaire",
                        feedback.question_template_id_id,
                    ),
                    tenant_id=tenant_id,
                ).first()
                if case is None or questionnaire is None:
                    skipped += 1
                    continue
                HrMultiRaterSession.objects.get_or_create(
                    id=self._stable_uuid(
                        tenant_id, "legacy-feedback-session", feedback.id
                    ),
                    defaults={
                        "tenant_id": tenant_id,
                        "case_id": case.id,
                        "session_name": feedback.review_cycle,
                        "questionnaire_version": questionnaire,
                        "anonymity_strategy": "IDENTIFIED",
                        "min_responses_json": {},
                        "session_status": (
                            "CLOSED" if feedback.status == "Closed" else "ACTIVE"
                        ),
                        "started_at": self._aware_boundary(feedback.start_date),
                        "closed_at": (
                            self._aware_boundary(feedback.end_date, end=True)
                            if feedback.status == "Closed" and feedback.end_date
                            else None
                        ),
                    },
                )
                migrated += 1
            return {"migrated": migrated, "skipped": skipped}
        except ImportError:
            return {"migrated": 0}

    def _migrate_answers(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import Answer
            from hr_assessment.models.evidence import (
                HrMultiRaterFeedback,
                HrMultiRaterSession,
            )

            scoped = Answer.objects.filter(
                employee_id__employee_work_info__company_id_id=tenant_id
            ).select_related("employee_id", "feedback_id", "question_id")
            if dry:
                return {"migrated": scoped.count(), "skipped": 0}
            migrated = 0
            skipped = 0
            for answer in scoped:
                reviewer = self._staff_for_legacy_employee(
                    tenant_id, answer.employee_id_id
                )
                session = HrMultiRaterSession.objects.filter(
                    tenant_id=tenant_id,
                    id=self._stable_uuid(
                        tenant_id, "legacy-feedback-session", answer.feedback_id_id
                    ),
                ).first()
                if reviewer is None or session is None:
                    skipped += 1
                    continue
                feedback_id = self._stable_uuid(
                    tenant_id,
                    "legacy-rater-feedback",
                    f"{session.id}:{reviewer.id}",
                )
                feedback, _ = HrMultiRaterFeedback.objects.get_or_create(
                    id=feedback_id,
                    defaults={
                        "session": session,
                        "reviewer_staff_id": reviewer.id,
                        "answers_json": [],
                        "submitted_at": session.closed_at,
                    },
                )
                entries = [
                    item
                    for item in (feedback.answers_json or [])
                    if str(item.get("legacyAnswerId")) != str(answer.id)
                ]
                entries.append(
                    {
                        "legacyAnswerId": str(answer.id),
                        "questionId": str(
                            self._stable_uuid(
                                tenant_id,
                                "legacy-question",
                                answer.question_id_id,
                            )
                        ),
                        "answer": answer.answer,
                    }
                )
                feedback.answers_json = entries
                feedback.save(update_fields=["answers_json"])
                migrated += 1
            return {"migrated": migrated, "skipped": skipped}
        except ImportError:
            return {"migrated": 0}

    def _migrate_question_templates(self, tenant_id: int, dry: bool) -> dict:
        try:
            from pms.models import QuestionTemplate
            from hr_assessment.models.evidence import (
                HrQuestionVersion,
                HrQuestionnaireVersion,
            )

            scoped = QuestionTemplate.objects.filter(company_id__id=tenant_id).distinct()
            if dry:
                return {"migrated": scoped.count(), "skipped": 0}
            migrated = 0
            for template in scoped.prefetch_related("question__question_options"):
                questionnaire, _ = HrQuestionnaireVersion.objects.get_or_create(
                    id=self._stable_uuid(
                        tenant_id, "legacy-questionnaire", template.id
                    ),
                    defaults={
                        "tenant_id": tenant_id,
                        "name": template.question_template,
                        "version_no": 1,
                        "status": "ARCHIVED",
                    },
                )
                for order, question in enumerate(template.question.all(), start=1):
                    options = []
                    option_row = question.question_options.first()
                    if option_row is not None:
                        options = [
                            value
                            for value in (
                                option_row.option_a,
                                option_row.option_b,
                                option_row.option_c,
                                option_row.option_d,
                            )
                            if value
                        ]
                    HrQuestionVersion.objects.get_or_create(
                        id=self._stable_uuid(
                            tenant_id, "legacy-question", question.id
                        ),
                        defaults={
                            "questionnaire": questionnaire,
                            "question_text": question.question,
                            "question_type": {
                                "1": "TEXT",
                                "2": "RATING",
                                "3": "BOOLEAN",
                                "4": "MULTI_CHOICE",
                                "5": "LIKERT",
                            }.get(str(question.question_type), "TEXT"),
                            "options_json": options,
                            "purpose": "LEGACY_MIGRATION",
                            "required": True,
                            "display_order": order,
                        },
                    )
                migrated += 1
            return {"migrated": migrated, "skipped": 0}
        except ImportError:
            return {"migrated": 0}
