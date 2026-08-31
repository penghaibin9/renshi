"""
hr_onboarding/services/portal_service.py

Portal（375px mobile-first，总册 §31.5/§34）：
- Portal 不接受任意 case id；只用 token 解析（HrPrehirePortalAccess）；
- Portal 数据只写 HrPrehireProfile staging，禁止直接写 HR03 权威表；
- 冲突（Portal 自填 vs HR04 已核验）生成 HrOnboardingDataConflict，不静默覆盖。
"""

from __future__ import annotations

from typing import Optional

from hr_onboarding.api.exceptions import Hr05ApiError
from hr_onboarding.models import (
    HrOnboardingDataConflict,
    HrPrehirePortalAccess,
    HrPrehireProfile,
)
from hr_onboarding.services.token_service import resolve_portal_access

# 冲突检测字段（Portal 可自填但与 HR04 来源冲突时须人工裁决）
CONFLICT_FIELDS = ("legal_name", "preferred_name")


def get_portal_by_token(*, tenant_id: Optional[int], token: str) -> HrPrehirePortalAccess:
    return resolve_portal_access(tenant_id=tenant_id, token=token)


def get_me(portal: HrPrehirePortalAccess) -> dict:
    """Portal 首页数据（本人 only；高敏字段遮罩）。"""
    from hr_onboarding.api.labels import CASE_STATUS_LABELS, VERIFICATION_STATUS_LABELS, label_for

    case = portal.case
    profile = HrPrehireProfile.objects.filter(case=case).first()
    return {
        "case_no": case.case_no,
        "legal_name": (profile.legal_name if profile else "") or case.case_no,
        "expected_report_date": case.expected_report_date.isoformat()
        if case.expected_report_date
        else None,
        "status": case.status,
        "statusLabel": label_for(CASE_STATUS_LABELS, case.status),
        "verification_status": profile.verification_status if profile else "UNVERIFIED",
        "verificationStatusLabel": label_for(
            VERIFICATION_STATUS_LABELS, profile.verification_status if profile else ""
        ),
    }


def update_profile(portal: HrPrehirePortalAccess, data: dict) -> dict:
    """
    更新 staging profile。legal_name 等字段与 HR04 来源值不一致 → 生成 DataConflict，
    不覆盖 HR04 值（避免静默覆盖，总册 §22）。
    """
    case = portal.case
    profile, _ = HrPrehireProfile.objects.get_or_create(tenant_id=case.tenant_id, case=case)

    for field in CONFLICT_FIELDS:
        new_value = (data.get(field) or "").strip()
        hr04_value = (getattr(profile, field) or "").strip()
        if new_value and hr04_value and new_value != hr04_value:
            existing = HrOnboardingDataConflict.objects.filter(
                case=case, field=field, resolution="OPEN"
            ).first()
            if existing is None:
                HrOnboardingDataConflict.objects.create(
                    tenant_id=case.tenant_id,
                    case=case,
                    field=field,
                    source_a="HR04",
                    source_b="PORTAL",
                    value_a=hr04_value,
                    value_b=new_value,
                    resolution="OPEN",
                )
            # 不覆盖 HR04 权威来源值
            continue
        if new_value:
            setattr(profile, field, new_value)

    other = data.get("other_fields")
    if other is not None:
        import json as _json

        # 大小限制：防恶意超大 JSON 打爆 DB
        try:
            raw = _json.dumps(other, ensure_ascii=False)
        except (TypeError, ValueError):
            raw = ""
        if len(raw) > 64 * 1024:
            raise Hr05ApiError("other_fields 超过 64KB 上限")
        if isinstance(other, dict):
            profile.other_fields_json = other
    # bank_json 为 HIGH_SENSITIVE：加密存储，不落明文
    bank_data = data.get("bank")
    if isinstance(bank_data, dict):
        from hr_onboarding.services.security import encrypt_sensitive_value

        profile.bank_json = encrypt_sensitive_value(bank_data)
    profile.version += 1
    profile.save()
    return get_me(portal)


def confirm_intent(portal: HrPrehirePortalAccess) -> dict:
    """Portal 确认入职意愿（由 case_service 状态机推进；Portal 侧 actor 为 SYSTEM/本人）。"""
    from hr_onboarding.services.case_service import CaseService

    case = portal.case
    service = CaseService(tenant_id=case.tenant_id, actor_user_id=None)
    service.confirm_intent(case)
    return get_me(portal)
