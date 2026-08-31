"""
hr_onboarding/models/case.py

HrOnboardingCase —— HR05 核心聚合根（总册 §7/§8/§10）。

关键语义（§8）：
- REPORTED = 报到动作完成；ACTIVE = HR03 生效；ONBOARDING_COMPLETED = 协同完成；CONFIRMED = 试用转正终局。
- 报到登记 ≠ 正式任职 ≠ 账号开通 ≠ 发薪起算；一个"已完成"必须能解释哪个环节还欠账。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import (
    ActivationStatus,
    CaseSourceType,
    CaseStatus,
    EmploymentType,
    PersonMatchStatus,
    ReportDelayApprovalStatus,
    StaffCategoryCode,
)


class HrOnboardingCase(models.Model):
    """Onboarding Case 聚合根。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case_no = models.CharField(max_length=64)
    # ---- 来源（00 §91 HANDOFF 边界）----
    source_type = models.CharField(max_length=32, choices=CaseSourceType.choices)
    source_id = models.CharField(max_length=128)
    hr04_proposed_hire_id = models.CharField(max_length=128, null=True, blank=True)
    hr04_application_id = models.CharField(max_length=128, null=True, blank=True)
    candidate_id = models.BigIntegerField(null=True, blank=True)  # legacy Candidate pk 映射
    person_match_status = models.CharField(
        max_length=24,
        choices=PersonMatchStatus.choices,
        default=PersonMatchStatus.NO_MATCH,
    )
    # ---- 计划组织/岗位（HR02 稳定 ID，00 §90）----
    planned_organization_id = models.ForeignKey(
        "hr_structure.HrOrganization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="onboarding_cases",
    )
    planned_post_catalog_id = models.ForeignKey(
        "hr_structure.HrPostCatalog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="onboarding_cases",
    )
    planned_position_id = models.ForeignKey(
        "hr_structure.HrPosition",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="onboarding_cases",
    )
    position_reservation_id = models.ForeignKey(
        "hr_structure.HrPositionReservation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="onboarding_cases",
    )
    employment_type = models.CharField(
        max_length=24,
        choices=EmploymentType.choices,
        default=EmploymentType.FULL_TIME,
    )
    staff_category = models.CharField(
        max_length=32,
        choices=StaffCategoryCode.choices,
        default=StaffCategoryCode.TEACHER,
    )
    # ---- 报到计划/事实 ----
    expected_report_date = models.DateField(null=True, blank=True)
    actual_report_at = models.DateTimeField(null=True, blank=True)
    # ---- 状态机 ----
    status = models.CharField(
        max_length=32,
        choices=CaseStatus.choices,
        default=CaseStatus.CREATED,
        db_index=True,
    )
    current_stage_code = models.CharField(max_length=64, blank=True, default="")
    activation_status = models.CharField(
        max_length=24,
        choices=ActivationStatus.choices,
        default=ActivationStatus.NOT_STARTED,
    )
    # ---- HR03 生效链接（UUID 引用，不建跨 app FK；00 §92）----
    hr03_person_id = models.UUIDField(null=True, blank=True)
    hr03_staff_master_id = models.UUIDField(null=True, blank=True)
    hr03_employment_id = models.UUIDField(null=True, blank=True)
    hr03_assignment_id = models.UUIDField(null=True, blank=True)
    template_version = models.ForeignKey(
        "hr_onboarding.HrOnboardingTemplateVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cases",
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Onboarding Case")
        verbose_name_plural = _("HR Onboarding Cases")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "case_no"],
                name="uniq_hr_ob_case_tenant_case_no",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "source_type", "source_id"],
                name="uniq_hr_ob_case_tenant_source",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "expected_report_date"]),
            models.Index(fields=["tenant_id", "actual_report_at"]),
            models.Index(
                fields=["tenant_id", "planned_organization_id", "status"],
                name="idx_hr_ob_case_org_status",
            ),
            models.Index(fields=["tenant_id", "current_stage_code"]),
        ]

    def __str__(self):
        return f"{self.case_no} [{self.status}]"


class HrOnboardingStageTransition(models.Model):
    """正式阶段历史 ledger（缺陷 B 修复，替代 OneToOne CandidateStage 当权威历史）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        HrOnboardingCase,
        on_delete=models.CASCADE,
        related_name="stage_transitions",
    )
    from_stage = models.CharField(max_length=32, blank=True, default="")
    to_stage = models.CharField(max_length=32)
    action = models.CharField(max_length=64, blank=True, default="")
    actor_user_id = models.BigIntegerField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Stage Transition")
        verbose_name_plural = _("HR Onboarding Stage Transitions")
        indexes = [
            models.Index(fields=["case", "occurred_at"]),
        ]
        ordering = ["occurred_at"]

    def __str__(self):
        return f"{self.case_id}: {self.from_stage} -> {self.to_stage}"


class HrReportDelay(models.Model):
    """延期报到（总册 §9.5/§66 禁止覆盖原日期）：保留 old/new 历史 + 审批。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        HrOnboardingCase,
        on_delete=models.CASCADE,
        related_name="report_delays",
    )
    old_date = models.DateField()
    new_date = models.DateField()
    reason = models.TextField(blank=True, default="")
    approval_status = models.CharField(
        max_length=16,
        choices=ReportDelayApprovalStatus.choices,
        default=ReportDelayApprovalStatus.PENDING,
    )
    requested_by = models.BigIntegerField(null=True, blank=True)
    decided_by = models.BigIntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Report Delay")
        verbose_name_plural = _("HR Onboarding Report Delays")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.case_id}: {self.old_date} -> {self.new_date}"


class HrReportCheckin(models.Model):
    """报到确认（总册 §10.4）：报到幂等（case+actual_report_at 唯一）。"""

    class Source(models.TextChoices):
        MANUAL = "MANUAL", _("Manual")
        PORTAL = "PORTAL", _("Portal")
        IMPORT = "IMPORT", _("Import")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        HrOnboardingCase,
        on_delete=models.PROTECT,
        related_name="report_checkins",
    )
    actual_report_at = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True, default="")
    checked_identity = models.BooleanField(default=False)
    operator_id = models.BigIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Onboarding Report Checkin")
        verbose_name_plural = _("HR Onboarding Report Checkins")
        constraints = [
            models.UniqueConstraint(
                fields=["case", "actual_report_at"],
                name="uniq_hr_ob_checkin_case_at",
            ),
        ]

    def __str__(self):
        return f"{self.case_id} @ {self.actual_report_at}"
