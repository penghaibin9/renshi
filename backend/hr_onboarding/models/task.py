"""
hr_onboarding/models/task.py

入职协同任务实例（总册 §14.2/§14.4）：
- assignee_type/assignee_id：责任人按角色解析（不存 template 级 Employee ID）；
- status 权威 9 态；completion_payload 记录完成证据；version 乐观锁。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_onboarding.constants import ResponsibleRole, TaskStatus


class HrOnboardingTaskInstance(models.Model):
    """任务实例（case + definition + cycle 唯一）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    case = models.ForeignKey(
        "hr_onboarding.HrOnboardingCase",
        on_delete=models.CASCADE,
        related_name="task_instances",
    )
    definition = models.ForeignKey(
        "hr_onboarding.HrOnboardingTaskDefinition",
        on_delete=models.PROTECT,
        related_name="instances",
    )
    cycle = models.CharField(max_length=16, default="INITIAL", blank=True)
    assignee_type = models.CharField(
        max_length=32,
        choices=ResponsibleRole.choices,
        default=ResponsibleRole.RESPONSIBLE_HR,
    )
    assignee_id = models.BigIntegerField(null=True, blank=True)  # 实例化时解析到的实际人员
    status = models.CharField(
        max_length=24,
        choices=TaskStatus.choices,
        default=TaskStatus.NOT_STARTED,
        db_index=True,
    )
    available_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_payload = models.JSONField(default=dict, blank=True)  # 完成人/时间/备注/证据
    failure_code = models.CharField(max_length=64, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Onboarding Task Instance")
        verbose_name_plural = _("HR Onboarding Task Instances")
        constraints = [
            models.UniqueConstraint(
                fields=["case", "definition", "cycle"],
                name="uniq_hr_ob_task_inst_case_def_cycle",
            ),
        ]
        indexes = [
            models.Index(fields=["case", "status"]),
            models.Index(fields=["assignee_id", "status", "due_at"]),
        ]

    def __str__(self):
        return f"{self.definition.code}:{self.status}"
