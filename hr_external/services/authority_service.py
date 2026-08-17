"""
hr_external/services/authority_service.py —— HR08 Authority 切换（S12，总册 §114/§57）。

模式：LEGACY_EMPLOYEE_TAG_ONLY → DUAL_READ_COMPARE → HR08_AUTHORITY。
- HR08_AUTHORITY 后：legacy 外聘写入口必须返回 HR08_LEGACY_WRITE_DISABLED（§114）；
- 禁止 silent fallback legacy（§57）：Provider 不可用不得回退旧 Employee。
"""

from __future__ import annotations

from typing import Optional

from django.utils import timezone

from hr_external.constants import ExternalAuthorityMode
from hr_external.models import HrExternalAuthorityConfig


class AuthorityTransitionInvalid(Exception):
    code = "VERSION_CONFLICT"


_TRANSITIONS = {
    ExternalAuthorityMode.LEGACY_EMPLOYEE_TAG_ONLY: {ExternalAuthorityMode.DUAL_READ_COMPARE},
    ExternalAuthorityMode.DUAL_READ_COMPARE: {ExternalAuthorityMode.HR08_AUTHORITY},
    ExternalAuthorityMode.HR08_AUTHORITY: set(),
}


class AuthorityService:
    @staticmethod
    def get_mode(tenant_id: int) -> str:
        cfg = HrExternalAuthorityConfig.objects.filter(tenant_id=tenant_id).first()
        return cfg.authority_mode if cfg else ExternalAuthorityMode.LEGACY_EMPLOYEE_TAG_ONLY

    @staticmethod
    def can_legacy_write(tenant_id: int) -> bool:
        cfg = HrExternalAuthorityConfig.objects.filter(tenant_id=tenant_id).first()
        if cfg and cfg.legacy_write_disabled:
            return False
        return AuthorityService.get_mode(tenant_id) != ExternalAuthorityMode.HR08_AUTHORITY

    def transition(
        self,
        *,
        tenant_id: int,
        target: str,
        actor_id: Optional[int] = None,
    ) -> HrExternalAuthorityConfig:
        current = AuthorityService.get_mode(tenant_id)
        if target not in _TRANSITIONS.get(current, set()):
            raise AuthorityTransitionInvalid(
                f"illegal authority transition {current} -> {target}"
            )
        cfg, _ = HrExternalAuthorityConfig.objects.get_or_create(
            tenant_id=tenant_id,
            defaults={
                "authority_mode": current,
                "legacy_write_disabled": current == ExternalAuthorityMode.HR08_AUTHORITY,
            },
        )
        cfg.authority_mode = target
        cfg.cutover_at = timezone.now()
        cfg.cutover_by = actor_id
        cfg.legacy_write_disabled = target == ExternalAuthorityMode.HR08_AUTHORITY
        cfg.save(
            update_fields=[
                "authority_mode",
                "cutover_at",
                "cutover_by",
                "legacy_write_disabled",
                "updated_at",
            ]
        )
        return cfg
