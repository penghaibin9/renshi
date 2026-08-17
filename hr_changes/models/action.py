"""
hr_changes/models/action.py —— HrChangeAction 异动动作定义（总册 §7/§78）。

动作可配置 enablement；V1 种子 16 个（见 CHANGE_ACTION_MATRIX）。
正式使用后不可物理删除（版本化停用）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_changes.constants import ChangeActionCode, ReportingManagerPolicy


class HrChangeAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=40, choices=ChangeActionCode.choices)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")

    # 启停：可配置 enablement（总册 §78），禁用后不能发起新 case（历史保留）
    enabled = models.BooleanField(default=True)

    # 动作策略
    # - is_temporary: 是否临时异动（SECONDMENT/ATTACHMENT）
    is_temporary = models.BooleanField(default=False)
    # - reporting_manager_policy（总册 §22）
    reporting_manager_policy = models.CharField(
        max_length=32,
        choices=ReportingManagerPolicy.choices,
        default=ReportingManagerPolicy.KEEP,
    )
    # - 生效日期规则（json：{min_days_from_today, allow_past, ...} 等；V1 由 validation_service 解释）
    effective_date_rule_json = models.JSONField(default=dict, blank=True)
    # - followup_policy_json（{domains: ["HR07","HR15","HR11"], event_types: [...]}）
    followup_policy_json = models.JSONField(default=dict, blank=True)

    # 可发起身份（总册 §18）：SELF/REPORTING_MANAGER/COLLEGE_HR/TARGET_ORG/SCHOOL_HR/RESTRUCTURE_ADMIN
    allowed_initiators_json = models.JSONField(default=list, blank=True)

    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Change Action")
        verbose_name_plural = _("HR Change Actions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_hr_change_action_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "enabled"]),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"
