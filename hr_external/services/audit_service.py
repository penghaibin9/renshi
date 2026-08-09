"""
hr_external/services/audit_service.py —— HrExternalAuditEvent 写入助手（S2，总册 §109）。

约束（00 §37/§45）：
- 日志禁止身份证完整号/银行卡/明文密码/文件内容/access token；
- before/after 用 snapshot_ref（引用/掩码快照），不内联高敏明文。
"""

from __future__ import annotations

from typing import Optional

from hr_external.models import HrExternalAuditEvent


def write_external_audit(
    *,
    tenant_id: int,
    action: str,
    actor_user_id: Optional[int] = None,
    external_profile_id=None,
    engagement_id=None,
    task_id=None,
    business_type: str = "",
    business_id: str = "",
    before_snapshot_ref: str = "",
    after_snapshot_ref: str = "",
    reason: str = "",
    source: str = "",
    request_id: str = "",
    ip=None,
    user_agent: str = "",
) -> HrExternalAuditEvent:
    """写入正式业务审计。调用方保证入参不含高敏明文。"""
    return HrExternalAuditEvent.objects.create(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        external_profile_id=external_profile_id,
        engagement_id=engagement_id,
        task_id=task_id,
        action=action,
        business_type=business_type,
        business_id=business_id,
        before_snapshot_ref=before_snapshot_ref,
        after_snapshot_ref=after_snapshot_ref,
        reason=reason,
        source=source,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )
