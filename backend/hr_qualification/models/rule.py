"""
hr_qualification/models/rule.py —— HrDoubleTeacherRule（总册 §37-38）。

结构化规则条目。
- 绑 RulePackVersion（版本冻结后规则不变）
- 规则类型：BOOLEAN_FACT / COUNT / DURATION / LEVEL_AT_LEAST / ONE_OF / ALL_OF / ANY_OF
  / DATE_VALID / ROLE_REQUIRED / AWARD_LEVEL / PROJECT_ROLE / EQUIVALENCY / MANUAL_COMMITTEE
- hard_or_soft：硬性/软性（HARD 不可降低；SOFT 可替代）
- expected_value_json：typed DSL，禁止 eval
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import (
    DoubleTeacherDimension,
    HardOrSoft,
    RecognitionLevel,
    RuleType,
)


class HrDoubleTeacherRule(models.Model):
    """双师认定规则条目。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRulePackVersion",
        on_delete=models.CASCADE,
        related_name="rules",
    )
    level = models.CharField(
        max_length=32,
        choices=RecognitionLevel.choices,
        db_index=True,
    )  # 适用层级（初/中/高）
    dimension_code = models.CharField(
        max_length=48,
        choices=DoubleTeacherDimension.choices,
        default=DoubleTeacherDimension.TEACHING_ABILITY,
    )
    rule_code = models.CharField(max_length=64)  # 业务唯一编码
    rule_type = models.CharField(
        max_length=24, choices=RuleType.choices, default=RuleType.BOOLEAN_FACT
    )
    # 操作符：>= / <= / == / IN / CONTAINS / EXISTS
    operator = models.CharField(max_length=16, blank=True, default=">=")
    # typed DSL（白名单，禁止 eval）
    expected_value_json = models.JSONField(null=True, blank=True)
    hard_or_soft = models.CharField(
        max_length=8, choices=HardOrSoft.choices, default=HardOrSoft.HARD
    )
    # 证据来源要求
    evidence_type = models.CharField(max_length=64, blank=True, default="")
    source_provider = models.CharField(max_length=64, blank=True, default="")
    manual_review_required = models.BooleanField(default=False)
    sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Rule")
        verbose_name_plural = _("HR Double Teacher Rules")
        indexes = [
            models.Index(fields=["version_id", "level", "dimension_code"]),
            models.Index(fields=["version_id", "rule_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.rule_code} [{self.level}] {self.rule_type}"
