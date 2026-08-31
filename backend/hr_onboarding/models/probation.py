"""
hr_onboarding/models/probation.py

试用与转正（总册 §17）：
- 不把试用期结束日期直接写 Candidate.probation_end；
- 延长创建 HrProbationExtension 保留历史，不覆盖 planned_end_date；
- 转正成功发 ProbationConfirmed + HR03 领域服务；失败走正式人事事件（HR07/HR16），
  不 Employee.is_active=False；终局后不可直接改。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import ProbationResult, ProbationStatus


class HrProbationCase(models.Model):
    """试用期事实（一次激活一份，同 employment 同一时刻最多一份进行中）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    onboarding_case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="probation_cases",
    )
    staff_master_id = models.UUIDField(null=True, blank=True)
    employment_relationship_id = models.UUIDField(null=True, blank=True)
    start_date = models.DateField()
    planned_end_date = models.DateField()
    actual_end_date = models.DateField(null=True, blank=True)
    policy_version_id = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=ProbationStatus.choices,
        default=ProbationStatus.NOT_STARTED,
        db_index=True,
    )
    result = models.CharField(
        max_length=16,
        choices=ProbationResult.choices,
        default=ProbationResult.NONE,
    )
    extension_count = models.PositiveIntegerField(default=0)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Probation Case")
        verbose_name_plural = _("HR Probation Cases")
        indexes = [
            models.Index(fields=["staff_master_id", "status"]),
        ]

    def __str__(self):
        return f"probation:{self.staff_master_id}:{self.status}"


class HrProbationGoal(models.Model):
    """试用目标（可按人员类别配置不同模板，总册 §17.3）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    probation_case = models.ForeignKey(
        HrProbationCase,
        on_delete=models.CASCADE,
        related_name="goals",
    )
    category = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    evaluator_role = models.CharField(max_length=64, blank=True, default="")
    evidence_required = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("HR Probation Goal")
        verbose_name_plural = _("HR Probation Goals")

    def __str__(self):
        return f"{self.title}"


class HrProbationExtension(models.Model):
    """试用期延长（保留历史，不覆盖 planned_end_date，总册 §17.5）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    probation_case = models.ForeignKey(
        HrProbationCase,
        on_delete=models.CASCADE,
        related_name="extensions",
    )
    old_end_date = models.DateField()
    new_end_date = models.DateField()
    reason = models.TextField(blank=True, default="")
    approval = models.CharField(max_length=16, blank=True, default="PENDING")
    created_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Probation Extension")
        verbose_name_plural = _("HR Probation Extensions")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.old_end_date} -> {self.new_end_date}"


class HrProbationReview(models.Model):
    """试用评价（员工自评 → 单位评价 → 人事审核，总册 §17.4）。"""

    class ReviewType(models.TextChoices):
        SELF = "SELF", _("Self")
        COLLEGE = "COLLEGE", _("College")
        HR = "HR", _("HR")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    probation_case = models.ForeignKey(
        HrProbationCase,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    review_type = models.CharField(max_length=16, choices=ReviewType.choices)
    reviewer_id = models.BigIntegerField(null=True, blank=True)
    content = models.TextField(blank=True, default="")
    decision = models.CharField(max_length=16, blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Probation Review")
        verbose_name_plural = _("HR Probation Reviews")

    def __str__(self):
        return f"{self.review_type}:{self.probation_case_id}"
