"""
hr_recruitment/models/qualification.py

HR04-04 资格审查（《04_HR04_总册》§11）。

HrQualificationRule（挂在 RuleSetVersion 下）→ 系统预检
HrQualificationReview（逐条结论）
HrQualificationDecision（最终决策，RETURNED≠DISQUALIFIED）

硬规则：
- 系统自动预检只能输出 PASS/FAIL/DATA_MISSING/NEEDS_MANUAL_REVIEW/NOT_APPLICABLE，
  不得默认作出最终"不合格"结论（§3.3/§11.5）。
- 最终资格结论必须记录人工审核人和依据。
- RETURNED = 材料缺失可补正；DISQUALIFIED = 明确不满足冻结条件（可进复核）。
- 规则版本 LOCKED 后不可变；旧申请不得被新条件重写（§51）。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import (
    QualificationDecisionType,
    RuleSeverity,
    RuleSystemResult,
)


class HrQualificationRule(models.Model):
    """资格条件规则（属于 HrQualificationRuleSetVersion）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    rule_set_version_id = models.ForeignKey(
        "hr_recruitment.HrQualificationRuleSetVersion",
        on_delete=models.CASCADE,
        related_name="rules",
        verbose_name=_("Rule Set Version"),
    )
    rule_code = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    rule_type = models.CharField(max_length=32, blank=True, default="")
    operator = models.CharField(max_length=16, blank=True, default="")
    expected_value_json = models.JSONField(default=dict, blank=True)
    severity = models.CharField(
        max_length=8, choices=RuleSeverity.choices, default=RuleSeverity.SOFT
    )
    evidence_requirement = models.TextField(blank=True, default="")
    sequence = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("Qualification Rule")
        verbose_name_plural = _("Qualification Rules")
        constraints = [
            models.UniqueConstraint(
                fields=["rule_set_version_id", "rule_code"],
                name="uniq_hr_qual_rule_version_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "rule_set_version_id", "sequence"]),
        ]

    def __str__(self):
        return f"{self.rule_code} {self.label}"


class HrQualificationReview(models.Model):
    """逐条系统预检 + 人工审核记录。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.CASCADE,
        related_name="qualification_reviews",
        verbose_name=_("Application"),
    )
    rule_id = models.ForeignKey(
        HrQualificationRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    system_result = models.CharField(
        max_length=24, choices=RuleSystemResult.choices, default=RuleSystemResult.DATA_MISSING
    )
    reviewer_result = models.CharField(
        max_length=24, choices=RuleSystemResult.choices, blank=True, default=""
    )
    reviewer_id = models.CharField(max_length=128, blank=True, default="")
    evidence_refs = models.JSONField(default=list, blank=True)
    note = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Qualification Review")
        verbose_name_plural = _("Qualification Reviews")
        indexes = [
            models.Index(fields=["tenant_id", "application_id", "rule_id"]),
        ]

    def __str__(self):
        return f"{self.application_id} {self.rule_id} system={self.system_result}"


class HrQualificationDecision(models.Model):
    """资格审查最终决策（RETURNED/DISQUALIFIED/QUALIFIED/WITHDRAWN/REOPEN_OVERRIDDEN）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.CASCADE,
        related_name="qualification_decisions",
        verbose_name=_("Application"),
    )
    decision = models.CharField(
        max_length=24, choices=QualificationDecisionType.choices
    )
    reason_code = models.CharField(max_length=64, blank=True, default="")
    reason_text = models.TextField(blank=True, default="")
    decided_by = models.CharField(max_length=128, blank=True, default="")
    decided_at = models.DateTimeField(auto_now_add=True)
    rule_set_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    missing_items = models.JSONField(default=list, blank=True)
    resubmit_deadline = models.DateTimeField(null=True, blank=True)
    supersedes_id = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = _("Qualification Decision")
        verbose_name_plural = _("Qualification Decisions")
        indexes = [
            models.Index(fields=["tenant_id", "application_id", "decided_at"]),
        ]

    def __str__(self):
        return f"{self.application_id} {self.decision}"
