"""
hr_recruitment/services/audit_service.py

审计写入（总册 §26）：不能只依赖 Horilla simple-history。

- HrRecruitmentAuditEvent：计划/公告/规则/申请/评分/回避/体检/拟录用/公示/异议/Offer/handoff；
- HrSensitiveCandidateAccessLog：候选敏感信息（身份证/简历/完整手机号）查看与下载审计。

日志红线（§1.1）：不得输出身份证/完整手机号/简历正文。
"""

from __future__ import annotations

from uuid import uuid4

from django.utils import timezone

from hr_recruitment.models import HrRecruitmentAuditEvent, HrSensitiveCandidateAccessLog


def audit_event(
    *,
    tenant_id: int,
    event_type: str,
    business_object: str = "",
    business_object_id: str = "",
    actor_id: str = "",
    action: str = "",
    summary: str = "",
    before: dict | None = None,
    after: dict | None = None,
    correlation_id: str = "",
    request_id: str = "",
) -> HrRecruitmentAuditEvent:
    """写一条领域审计事件（before/after 只存业务字段，禁止存身份证/简历等敏感明文）。"""
    return HrRecruitmentAuditEvent.objects.create(
        tenant_id=tenant_id,
        event_type=event_type,
        business_object=business_object,
        business_object_id=str(business_object_id),
        actor_id=actor_id,
        action=action,
        summary=summary[:300],
        before_json=before or {},
        after_json=after or {},
        correlation_id=correlation_id,
        request_id=request_id,
    )


def log_sensitive_access(
    *,
    tenant_id: int,
    candidate_id,
    access_type: str,  # VIEW / DOWNLOAD / EXPORT
    sensitive_field: str = "",
    material_id=None,
    actor_id: str = "",
    reason: str = "",
    request_id: str = "",
) -> HrSensitiveCandidateAccessLog:
    """记录候选敏感信息访问（身份证/简历/完整手机号查看与下载）。"""
    return HrSensitiveCandidateAccessLog.objects.create(
        tenant_id=tenant_id,
        candidate_id=candidate_id,
        access_type=access_type,
        sensitive_field=sensitive_field,
        material_id=material_id,
        actor_id=actor_id,
        reason=reason[:500],
        request_id=request_id,
    )
