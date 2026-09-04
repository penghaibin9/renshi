"""Canonical HR04 application todos for the HR01 workbench."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db.models import Q

from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoProviderUnavailable,
    TodoSummary,
)
from hr_recruitment.constants import ApplicationCanonicalStatus


_TERMINAL = {
    ApplicationCanonicalStatus.DRAFT,
    ApplicationCanonicalStatus.DISQUALIFIED,
    ApplicationCanonicalStatus.ASSESSMENT_FAILED,
    ApplicationCanonicalStatus.OFFER_ACCEPTED,
    ApplicationCanonicalStatus.OFFER_DECLINED,
    ApplicationCanonicalStatus.HANDOFF_TO_HR05,
    ApplicationCanonicalStatus.WITHDRAWN,
    ApplicationCanonicalStatus.CANCELLED,
}

_STAGE_LABELS = {
    "SUBMITTED": "待受理",
    "UNDER_REVIEW": "资格审查",
    "RETURNED": "待补充材料",
    "RESUBMITTED": "重新审查",
    "QUALIFIED": "资格通过",
    "ASSESSMENT_PENDING": "待考试面试",
    "ASSESSING": "考试面试中",
    "ASSESSMENT_PASSED": "考核通过",
    "MEDICAL_PENDING": "待体检",
    "MEDICAL_REVIEW": "体检复核",
    "BACKGROUND_PENDING": "待考察",
    "BACKGROUND_REVIEW": "考察复核",
    "PROPOSED_HIRE": "拟录用",
    "PUBLIC_NOTICE": "公示中",
    "OFFER_PENDING": "待发录用通知",
    "OFFERED": "等待应聘者确认",
}


class RecruitmentApplicationTodoProvider(HrTodoProvider):
    provider_key = "hr04_recruitment"
    required_permission = "hr.recruitment.application.view"

    @staticmethod
    def _assert_current(context) -> None:
        if not context.tenant_id:
            raise TodoProviderUnavailable(
                "hr04_recruitment", "TENANT_CONTEXT_REQUIRED", "缺少学校租户"
            )
        if context.as_of != context.today():
            raise TodoProviderUnavailable(
                "hr04_recruitment",
                "HISTORICAL_TODO_UNAVAILABLE",
                "招聘待办只提供当前任务",
            )

    def _qs(self, context):
        from hr_recruitment.models import HrJobApplication

        self._assert_current(context)
        query = HrJobApplication.objects.filter(
            tenant_id=context.tenant_id,
            is_active=True,
        ).exclude(canonical_status__in=_TERMINAL)
        if context.user_id:
            query = query.filter(
                Q(current_owner_id="") | Q(current_owner_id=str(context.user_id))
            )
        return query

    @staticmethod
    def _day_bounds(context):
        today = context.today()
        start = datetime.combine(today, time.min, tzinfo=context.tzinfo())
        return start, start + timedelta(days=1), start + timedelta(days=8)

    def get_summary(self, context) -> TodoSummary:
        query = self._qs(context)
        start, tomorrow, week_end = self._day_bounds(context)
        return TodoSummary(
            total=query.count(),
            overdue=query.filter(due_at__lt=start).count(),
            today=query.filter(due_at__gte=start, due_at__lt=tomorrow).count(),
            week=query.filter(due_at__gte=start, due_at__lt=week_end).count(),
        )

    def _to_item(self, application, context) -> TodoItem:
        due_at = application.due_at
        candidate = application.candidate_id
        position = application.recruitment_position_id
        stage = _STAGE_LABELS.get(
            application.canonical_status,
            application.workflow_stage_name or application.canonical_status,
        )
        overdue = bool(due_at and due_at < context.now())
        return TodoItem(
            provider=self.provider_key,
            business_type="recruitment_application",
            business_id=str(application.id),
            title=f"招聘申请：{application.application_no or application.id}",
            subject_name=candidate.legal_name,
            org_name=position.organization_name,
            current_stage=stage,
            severity="HIGH" if overdue else "MEDIUM",
            submitted_at=application.submitted_at or application.created_at,
            due_at=due_at,
            is_overdue=overdue,
            assignee_type="CURRENT_OWNER",
            action_label="办理招聘申请",
            action_url="/hr/recruitment/qualification",
            permission_code=self.required_permission,
            version=str(application.version),
        )

    def list_todos(self, context, filters=None, page=1, page_size=20):
        query = self._qs(context).select_related(
            "candidate_id", "recruitment_position_id"
        ).order_by("due_at", "submitted_at", "created_at")
        total = query.count()
        start = (page - 1) * page_size
        items = [
            self._to_item(application, context).__dict__
            for application in query[start : start + page_size]
        ]
        return {"items": items, "total": total, "available": True}
