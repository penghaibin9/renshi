"""
hr_staff/services/audit_service.py —— HrStaffAuditEvent 写入助手（总册 §28）。

约束：
- 日志禁止记录身份证完整号、银行卡、明文密码、文件完整内容、access token；
- before/after 用 snapshot_ref（引用/掩码快照），不内联高敏明文。
"""

from __future__ import annotations

from typing import Optional

from hr_staff.models import HrStaffAuditEvent


def write_audit_event(
    *,
    tenant_id: int,
    action: str,
    actor_user_id: Optional[int] = None,
    staff_id=None,
    person_id=None,
    business_type: str = "",
    business_id: str = "",
    before_snapshot_ref: str = "",
    after_snapshot_ref: str = "",
    reason: str = "",
    source: str = "",
    request_id: str = "",
    ip=None,
    user_agent: str = "",
) -> HrStaffAuditEvent:
    """写入正式业务审计。调用方保证入参不含高敏明文。"""
    return HrStaffAuditEvent.objects.create(
        tenant_id=tenant_id,
        staff_id=staff_id,
        person_id=person_id,
        actor_user_id=actor_user_id,
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
