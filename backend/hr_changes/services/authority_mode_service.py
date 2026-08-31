"""
hr_changes/services/authority_mode_service.py —— Authority 模式（S12，00 §56）。

合法顺序：LEGACY_ACTIVE → DUAL_READ_COMPARE → HR06_AUTHORITY → LEGACY_READONLY_PROJECTION。
- 不合法跳跃 → 拒绝；
- 切换显式审计（记录 + transition 语义由命令完成）；
- 禁止 silent fallback 到 legacy。
"""

from __future__ import annotations

from typing import Optional

from hr_changes.models import HrChangeAuthorityMode

_VALID_SEQUENCE = [
    HrChangeAuthorityMode.Mode.LEGACY_ACTIVE,
    HrChangeAuthorityMode.Mode.DUAL_READ_COMPARE,
    HrChangeAuthorityMode.Mode.HR06_AUTHORITY,
    HrChangeAuthorityMode.Mode.LEGACY_READONLY_PROJECTION,
]


class AuthorityModeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class AuthorityModeService:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def get_mode(self) -> str:
        row = HrChangeAuthorityMode.objects.filter(tenant_id=self.tenant_id).first()
        return row.mode if row else HrChangeAuthorityMode.Mode.LEGACY_ACTIVE

    def switch(
        self, target_mode: str, *, actor_user_id: Optional[int] = None, note: str = ""
    ) -> HrChangeAuthorityMode:
        current = self.get_mode()
        idx = _VALID_SEQUENCE.index(current)
        target_idx = _VALID_SEQUENCE.index(target_mode)
        if target_idx != idx + 1:
            raise AuthorityModeError(
                "AUTHORITY_MODE_INVALID",
                f"Authority 只能顺序推进：{current} → {_VALID_SEQUENCE[target_idx]}",
            )
        row, _ = HrChangeAuthorityMode.objects.update_or_create(
            tenant_id=self.tenant_id,
            defaults={
                "mode": target_mode,
                "switched_by": actor_user_id,
                "note": note,
            },
        )
        return row
