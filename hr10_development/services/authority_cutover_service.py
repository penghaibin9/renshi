"""
hr10_development/services/authority_cutover_service.py

Authority 切换服务（S12）。

LEGACY_OR_NONE → HR10_STAGING → DUAL_READ_COMPARE → HR10_AUTHORITY → LEGACY_READONLY_PROJECTION → POST_CUTOVER_CLEANUP

每个 tenant 独立维护 authority mode。
"""

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class AuthorityMode(Enum):
    LEGACY_OR_NONE = "LEGACY_OR_NONE"
    HR10_STAGING = "HR10_STAGING"
    DUAL_READ_COMPARE = "DUAL_READ_COMPARE"
    HR10_AUTHORITY = "HR10_AUTHORITY"
    LEGACY_READONLY = "LEGACY_READONLY"
    POST_CUTOVER_CLEANUP = "POST_CUTOVER_CLEANUP"


@dataclass
class CutoverState:
    tenant_id: int
    current_mode: AuthorityMode
    legacy_write_frozen: bool
    drift_acceptable: bool
    rollback_point: AuthorityMode | None = None


class AuthorityCutoverService:
    """
    Authority 切换编排服务。

    禁止：
    - 同一 tenant 同时有两个 formal write authority
    - DUAL_READ_COMPARE 阶段 drift 未解释就切到 HR10_AUTHORITY
    - HR10_AUTHORITY 模式下仍然允许 legacy 写入口
    """

    _tenant_modes: ClassVar[dict[int, CutoverState]] = {}

    @classmethod
    def get_mode(cls, tenant_id: int) -> CutoverState:
        return cls._tenant_modes.get(
            tenant_id,
            CutoverState(tenant_id=tenant_id, current_mode=AuthorityMode.LEGACY_OR_NONE,
                         legacy_write_frozen=False, drift_acceptable=False),
        )

    @classmethod
    def transition(cls, tenant_id: int, target: AuthorityMode) -> bool:
        """执行租户级权威模式切换。"""
        current = cls.get_mode(tenant_id)

        VALID_TRANSITIONS = {
            AuthorityMode.LEGACY_OR_NONE: [AuthorityMode.HR10_STAGING],
            AuthorityMode.HR10_STAGING: [AuthorityMode.DUAL_READ_COMPARE],
            AuthorityMode.DUAL_READ_COMPARE: [AuthorityMode.HR10_AUTHORITY],
            AuthorityMode.HR10_AUTHORITY: [AuthorityMode.LEGACY_READONLY],
            AuthorityMode.LEGACY_READONLY: [AuthorityMode.POST_CUTOVER_CLEANUP],
            AuthorityMode.POST_CUTOVER_CLEANUP: [],  # 终态
        }

        if target not in VALID_TRANSITIONS.get(current.current_mode, []):
            return False

        # DUAL_READ_COMPARE → HR10_AUTHORITY 前置：drift 必须可接受
        if target == AuthorityMode.HR10_AUTHORITY:
            if not current.drift_acceptable:
                return False

        # 切换到 HR10_AUTHORITY 时冻结 legacy 写
        if target in (AuthorityMode.HR10_AUTHORITY, AuthorityMode.LEGACY_READONLY):
            current.legacy_write_frozen = True
            current.rollback_point = current.current_mode

        current.current_mode = target
        cls._tenant_modes[tenant_id] = current
        return True

    @classmethod
    def rollback(cls, tenant_id: int) -> bool:
        """回退到上一个模式。"""
        current = cls.get_mode(tenant_id)
        if current.rollback_point:
            cls._tenant_modes[tenant_id] = CutoverState(
                tenant_id=tenant_id,
                current_mode=current.rollback_point,
                legacy_write_frozen=False,
                drift_acceptable=False,
            )
            return True
        return False

    @classmethod
    def is_hr10_authority(cls, tenant_id: int) -> bool:
        return cls.get_mode(tenant_id).current_mode in (
            AuthorityMode.HR10_AUTHORITY, AuthorityMode.LEGACY_READONLY
        )
