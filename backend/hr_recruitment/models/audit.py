"""
hr_recruitment/models/audit.py

HR04 专项审计（《04_HR04_总册》§26）。

不能只依赖 Horilla simple-history（§26）：
- HrRecruitmentAuditEvent：计划/公告/规则/申请/评分/回避/体检/拟录用/公示/异议/Offer/handoff/敏感访问。
- HrSensitiveCandidateAccessLog：候选敏感信息（身份证/简历/完整手机号）查看与下载审计。

日志红线（§1.1）：不得输出身份证/完整手机号/简历正文。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrRecruitmentAuditEvent(models.Model):
    """HR04 领域审计事件。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    business_object = models.CharField(max_length=64, blank=True, default="")
    business_object_id = models.CharField(max_length=128, blank=True, default="")
    actor_id = models.CharField(max_length=128, blank=True, default="")
    action = models.CharField(max_length=64, blank=True, default="")
    summary = models.CharField(max_length=300, blank=True, default="")
    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=128, blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Recruitment Audit Event")
        verbose_name_plural = _("Recruitment Audit Events")
        indexes = [
            models.Index(fields=["tenant_id", "event_type"]),
            models.Index(fields=["tenant_id", "business_object", "business_object_id"]),
            models.Index(fields=["tenant_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} {self.business_object} {self.action}"


class HrSensitiveCandidateAccessLog(models.Model):
    """候选敏感信息访问审计（身份证/简历/完整手机号查看与下载）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    candidate_id = models.UUIDField(db_index=True)
    access_type = models.CharField(max_length=32)  # VIEW / DOWNLOAD / EXPORT
    sensitive_field = models.CharField(max_length=64, blank=True, default="")
    material_id = models.UUIDField(null=True, blank=True)
    actor_id = models.CharField(max_length=128, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    request_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Sensitive Candidate Access Log")
        verbose_name_plural = _("Sensitive Candidate Access Logs")
        indexes = [
            models.Index(fields=["tenant_id", "candidate_id", "created_at"]),
            models.Index(fields=["tenant_id", "actor_id"]),
        ]

    def __str__(self):
        return f"{self.candidate_id} {self.access_type} {self.sensitive_field}"
