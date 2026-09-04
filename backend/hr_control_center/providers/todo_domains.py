"""Thin HR06-HR16 todo adapters over each domain's authoritative queue.

The adapter only reads tenant-scoped state. It never advances a workflow, so
HR01 remains an aggregation surface rather than a second approval engine.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.apps import apps
from django.db import models
from django.db.models import Q

from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoProviderUnavailable,
    TodoSummary,
)


class AuthorityQueueTodoProvider(HrTodoProvider):
    app_label = ""
    model_name = ""
    status_field = "status"
    active_statuses: frozenset[str] = frozenset()
    due_field = ""
    submitted_field = "created_at"
    identifier_field = "id"
    owner_field = ""
    title_prefix = "业务待办"
    business_type = "authority_case"
    action_label = "去办理"
    action_url = "/hr/overview"
    stage_labels: dict[str, str] = {}
    severity_field = ""

    def _assert_current(self, context) -> None:
        if not context.tenant_id:
            raise TodoProviderUnavailable(
                self.provider_key, "TENANT_CONTEXT_REQUIRED", "缺少学校租户"
            )
        if context.as_of != context.today():
            raise TodoProviderUnavailable(
                self.provider_key,
                "HISTORICAL_TODO_UNAVAILABLE",
                "业务待办只提供当前任务",
            )

    def _model(self):
        try:
            return apps.get_model(self.app_label, self.model_name)
        except LookupError as exc:
            raise TodoProviderUnavailable(
                self.provider_key,
                "MODULE_NOT_AVAILABLE",
                f"{self.app_label} 模块未启用",
            ) from exc

    def _qs(self, context):
        self._assert_current(context)
        query = self._model().objects.filter(tenant_id=context.tenant_id)
        if self.active_statuses:
            query = query.filter(**{f"{self.status_field}__in": self.active_statuses})
        if self.owner_field and context.user_id:
            query = query.filter(
                Q(**{self.owner_field: context.user_id})
                | Q(**{f"{self.owner_field}__isnull": True})
            )
        return query

    def _due_is_datetime(self) -> bool:
        if not self.due_field:
            return False
        return isinstance(
            self._model()._meta.get_field(self.due_field), models.DateTimeField
        )

    @staticmethod
    def _day_bounds(context):
        start = datetime.combine(context.today(), time.min, tzinfo=context.tzinfo())
        return start, start + timedelta(days=1), start + timedelta(days=8)

    def get_summary(self, context) -> TodoSummary:
        query = self._qs(context)
        if not self.due_field:
            return TodoSummary(total=query.count())
        if self._due_is_datetime():
            start, tomorrow, week_end = self._day_bounds(context)
            return TodoSummary(
                total=query.count(),
                overdue=query.filter(**{f"{self.due_field}__lt": start}).count(),
                today=query.filter(
                    **{
                        f"{self.due_field}__gte": start,
                        f"{self.due_field}__lt": tomorrow,
                    }
                ).count(),
                week=query.filter(
                    **{
                        f"{self.due_field}__gte": start,
                        f"{self.due_field}__lt": week_end,
                    }
                ).count(),
            )
        today = context.today()
        return TodoSummary(
            total=query.count(),
            overdue=query.filter(**{f"{self.due_field}__lt": today}).count(),
            today=query.filter(**{self.due_field: today}).count(),
            week=query.filter(
                **{
                    f"{self.due_field}__gte": today,
                    f"{self.due_field}__lte": today + timedelta(days=7),
                }
            ).count(),
        )

    def _as_datetime(self, value, context):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=context.tzinfo())
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.max, tzinfo=context.tzinfo())
        return None

    def _to_item(self, row, context) -> TodoItem:
        status = str(getattr(row, self.status_field, "") or "")
        identifier = str(getattr(row, self.identifier_field, "") or row.pk)
        due_at = self._as_datetime(
            getattr(row, self.due_field, None) if self.due_field else None,
            context,
        )
        submitted_at = self._as_datetime(
            getattr(row, self.submitted_field, None), context
        )
        overdue = bool(due_at and due_at < context.now())
        source_severity = (
            str(getattr(row, self.severity_field, "") or "").upper()
            if self.severity_field
            else ""
        )
        severity = (
            source_severity
            if source_severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
            else ("HIGH" if overdue else "MEDIUM")
        )
        return TodoItem(
            provider=self.provider_key,
            business_type=self.business_type,
            business_id=str(row.pk),
            title=f"{self.title_prefix}：{identifier}",
            current_stage=self.stage_labels.get(status, status),
            severity=severity,
            submitted_at=submitted_at,
            due_at=due_at,
            is_overdue=overdue,
            assignee_type="DOMAIN_OWNER",
            action_label=self.action_label,
            action_url=self.action_url,
            permission_code=self.required_permission,
            version=str(getattr(row, "version", 1)),
        )

    def list_todos(self, context, filters=None, page=1, page_size=20):
        query = self._qs(context)
        ordering = []
        if self.due_field:
            ordering.append(models.F(self.due_field).asc(nulls_last=True))
        ordering.append(self.submitted_field)
        query = query.order_by(*ordering)
        total = query.count()
        start = (page - 1) * page_size
        items = [
            self._to_item(row, context).__dict__
            for row in query[start : start + page_size]
        ]
        return {"items": items, "total": total, "available": True}


class PersonnelChangeTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr06_change"
    app_label = "hr_changes"
    model_name = "HrPersonnelChangeCase"
    active_statuses = frozenset(
        {
            "SUBMITTED", "UNDER_APPROVAL", "RETURNED", "RESUBMITTED",
            "APPROVED_WAITING_EFFECTIVE", "APPLYING", "APPLY_FAILED",
        }
    )
    due_field = "requested_effective_at"
    submitted_field = "submitted_at"
    identifier_field = "case_no"
    owner_field = "owner_id"
    title_prefix = "人事异动"
    business_type = "personnel_change"
    action_label = "办理异动"
    action_url = "/hr/changes/"
    required_permission = "hr.change.view"


class ContractCaseTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr07_contract"
    app_label = "hr_contracts"
    model_name = "HrContractCase"
    active_statuses = frozenset({"SUBMITTED", "RETURNED", "APPROVED", "EFFECT_PENDING"})
    due_field = "requested_effective_from"
    identifier_field = "case_no"
    title_prefix = "合同办理"
    business_type = "contract_case"
    action_label = "办理合同"
    action_url = "/hr/contracts/"
    required_permission = "hr.contracts.agreement.view"


class ExternalRenewalTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr08_external"
    app_label = "hr_external"
    model_name = "HrExternalRenewalReview"
    active_statuses = frozenset({"DRAFT", "IN_REVIEW"})
    due_field = "review_due_at"
    identifier_field = "engagement_id_id"
    title_prefix = "外聘续聘复核"
    business_type = "external_renewal"
    action_label = "办理续聘"
    action_url = "/hr/external-teachers/renewals/"
    required_permission = "hr.external.renewal.review"


class QualificationRiskTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr09_qualification"
    app_label = "hr_qualification"
    model_name = "HrQualificationRiskCase"
    active_statuses = frozenset({"OPEN", "ACKNOWLEDGED", "IN_PROGRESS"})
    due_field = "due_at"
    submitted_field = "opened_at"
    identifier_field = "risk_type"
    severity_field = "severity"
    title_prefix = "资格风险"
    business_type = "qualification_risk"
    action_label = "处置风险"
    action_url = "/hr/qualifications/risks/"
    required_permission = "hr.qualification.risk.view"


class DevelopmentRiskTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr10_development"
    app_label = "hr10_development"
    model_name = "HrDevelopmentRiskCase"
    active_statuses = frozenset({"OPEN", "ACKNOWLEDGED", "IN_PROGRESS"})
    due_field = "due_at"
    submitted_field = "detected_at"
    identifier_field = "risk_type"
    owner_field = "owner_id"
    severity_field = "severity"
    title_prefix = "教师发展风险"
    business_type = "development_risk"
    action_label = "处置风险"
    action_url = "/hr/development/dashboard"
    required_permission = "hr.development.analytics.read"


class AttendanceExceptionTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr11_time"
    app_label = "hr_time"
    model_name = "HrAttendanceException"
    active_statuses = frozenset({"OPEN", "REVIEWING"})
    due_field = "business_date"
    identifier_field = "exception_code"
    title_prefix = "考勤异常"
    business_type = "attendance_exception"
    action_label = "核验考勤"
    action_url = "/hr/time/attendance/"
    required_permission = "hr.time.attendance.manage"


class AssessmentReviewTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr12_assessment"
    app_label = "hr_assessment"
    model_name = "HrReviewerAssignment"
    active_statuses = frozenset({"PENDING", "ACCEPTED", "IN_PROGRESS"})
    due_field = "due_at"
    submitted_field = "assigned_at"
    identifier_field = "case_id"
    title_prefix = "考核评议"
    business_type = "assessment_review"
    action_label = "进入评议"
    action_url = "/hr/assessments/review/"
    required_permission = "hr.assessment.hr_reviewer"


class TitleReviewTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr13_title"
    app_label = "hr_title"
    model_name = "TitleReviewAssignment"
    active_statuses = frozenset({"ASSIGNED", "ACCEPTED"})
    submitted_field = "assigned_at"
    identifier_field = "assignment_no"
    title_prefix = "职称评审"
    business_type = "title_review"
    action_label = "进入评审"
    action_url = "/hr/titles/deliberation/"
    required_permission = "hr.title.panel"


class AppointmentCaseTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr14_appointment"
    app_label = "hr_appointment"
    model_name = "AppointmentApplicationCase"
    active_statuses = frozenset(
        {"SUBMITTED", "RETURNED", "ELIGIBLE", "UNDER_REVIEW", "PROPOSED", "PUBLICITY", "EFFECT_PENDING"}
    )
    identifier_field = "case_no"
    title_prefix = "岗位聘任"
    business_type = "appointment_case"
    action_label = "办理聘任"
    action_url = "/hr/appointments/applications/"
    required_permission = "hr.appointment.view"


class PayrollPeriodTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr15_payroll"
    app_label = "hr_payroll"
    model_name = "PayrollPeriod"
    active_statuses = frozenset({"OPEN", "INPUT_FROZEN", "CALCULATED", "REVIEWED", "FINALIZED"})
    due_field = "end_date"
    identifier_field = "period_code"
    title_prefix = "工资期间"
    business_type = "payroll_period"
    action_label = "办理工资"
    action_url = "/hr/payroll/calculations/"
    required_permission = "hr.payroll.view"


class ExitCaseTodoProvider(AuthorityQueueTodoProvider):
    provider_key = "hr16_exit"
    app_label = "hr_exit"
    model_name = "ExitCase"
    active_statuses = frozenset(
        {"SUBMITTED", "RETURNED", "APPROVED", "HANDOVER", "SETTLEMENT", "EFFECT_PENDING"}
    )
    due_field = "requested_date"
    identifier_field = "case_no"
    title_prefix = "退休离校"
    business_type = "exit_case"
    action_label = "办理离校"
    action_url = "/hr/exit/cases/"
    required_permission = "hr.exit.view"


CANONICAL_DOMAIN_TODO_PROVIDERS = (
    PersonnelChangeTodoProvider,
    ContractCaseTodoProvider,
    ExternalRenewalTodoProvider,
    QualificationRiskTodoProvider,
    DevelopmentRiskTodoProvider,
    AttendanceExceptionTodoProvider,
    AssessmentReviewTodoProvider,
    TitleReviewTodoProvider,
    AppointmentCaseTodoProvider,
    PayrollPeriodTodoProvider,
    ExitCaseTodoProvider,
)
