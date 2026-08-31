"""
hr_onboarding/policies/authority.py

HR05 authority_mode 读取（00 §56-§57 / 05 §44）：
- 无记录 → LEGACY_ONBOARDING_ONLY（默认，fail-closed 到 legacy 语义，但绝不 silent fallback）；
- HR05_AUTHORITY 后 Provider 故障不得自动回退 legacy。
"""

from __future__ import annotations

from typing import Optional


def get_authority_mode(tenant_id: int) -> str:
    """读取 tenant 的 authority mode（无记录默认 LEGACY_ONBOARDING_ONLY）。"""
    from hr_onboarding.models import HrOnboardingAuthorityMode

    record = HrOnboardingAuthorityMode.objects.filter(tenant_id=tenant_id).first()
    if record is None:
        return HrOnboardingAuthorityMode.Mode.LEGACY_ONBOARDING_ONLY
    return record.mode


def is_authority(tenant_id: int) -> bool:
    """是否已进入 HR05_AUTHORITY。"""
    from hr_onboarding.models import HrOnboardingAuthorityMode

    return get_authority_mode(tenant_id) == HrOnboardingAuthorityMode.Mode.HR05_AUTHORITY


def legacy_write_disabled(tenant_id: int) -> bool:
    """HR05_AUTHORITY 后 legacy 正式写入口应关闭（返回 True 表示禁止写 legacy）。"""
    return is_authority(tenant_id)


def switch_authority_mode(
    *,
    tenant_id: int,
    target_mode: str,
    operator_user_id: Optional[int] = None,
    reason: str = "",
    reconcile_report_id: str = "",
):
    """
    切换 authority mode（幂等：同 tenant+target 重复调用不重复记录切换历史由审计承载）。
    记录 old/new/operator/reason/reconcile_report_id。
    """
    from hr_onboarding.models import HrOnboardingAuthorityMode

    record, _ = HrOnboardingAuthorityMode.objects.get_or_create(
        tenant_id=tenant_id,
        defaults={
            "mode": target_mode,
            "old_mode": HrOnboardingAuthorityMode.Mode.LEGACY_ONBOARDING_ONLY,
            "new_mode": target_mode,
            "switched_by": operator_user_id,
            "reason": reason,
            "reconcile_report_id": reconcile_report_id,
        },
    )
    if record.mode == target_mode:
        return record
    record.old_mode = record.mode
    record.new_mode = target_mode
    record.mode = target_mode
    record.switched_by = operator_user_id
    record.reason = reason
    record.reconcile_report_id = reconcile_report_id
    record.save(
        update_fields=["mode", "old_mode", "new_mode", "switched_by", "reason", "reconcile_report_id"]
    )
    return record
