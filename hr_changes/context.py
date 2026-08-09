"""
hr_changes/context.py —— HR06 请求上下文（S1）。

硬合同（总册 §45 + 00 §8/§9 + HR01 context）：
- 无 tenant context → fail-closed（403 TENANT_CONTEXT_REQUIRED），不做全校兜底。
- "今天"按学校时区（school_timezone），禁止 date.today() 直用。
- scope 必须服务端重新验证，不信任前端参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date

from hr_changes.constants import ChangeScopeType

DEFAULT_SCHOOL_TZ = "Asia/Shanghai"


class HrChangeContextError(Exception):
    """HR06 上下文错误（tenant/scope 解析失败）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class HrChangeScope:
    """HR06 数据范围（总册 §42）。"""

    scope_type: str  # SCHOOL/COLLEGE/ORGANIZATION/SELF/ASSIGNED_CASES/SOURCE_ORG/TARGET_ORG
    org_id: Optional[int] = None
    label: str = ""

    @property
    def fingerprint(self) -> str:
        return f"hr06:{self.scope_type}:{self.org_id or ''}"


@dataclass(frozen=True)
class HrChangeRequestContext:
    tenant_id: Optional[int]
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    as_of: Optional[date] = None
    scope: HrChangeScope = field(default_factory=lambda: HrChangeScope(ChangeScopeType.SCHOOL))
    request_snapshot_at: Optional[datetime] = None

    def __post_init__(self):
        if self.request_snapshot_at is None:
            object.__setattr__(self, "request_snapshot_at", dj_timezone.now())
        if self.as_of is None:
            object.__setattr__(self, "as_of", self.today())

    def today(self) -> date:
        """当前学校时区的今天。禁止任何 selector 直接使用 date.today()。"""
        local_now = self.request_snapshot_at.astimezone(self.tzinfo())
        return local_now.date()

    def tzinfo(self):
        try:
            import zoneinfo

            return zoneinfo.ZoneInfo(self.school_timezone)
        except Exception:
            from zoneinfo import ZoneInfo

            return ZoneInfo(DEFAULT_SCHOOL_TZ)

    def scope_fingerprint(self) -> str:
        return self.scope.fingerprint


def build_hr_change_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    as_of: Optional[str] = None,
    scope_type: str = "SCHOOL",
    scope_org_id: Optional[int] = None,
) -> HrChangeRequestContext:
    """从 HTTP 参数构造 HrChangeRequestContext（服务端必须重新验证 scope，不信任前端参数）。"""
    if not tenant_id:
        raise HrChangeContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）")

    def _p(s):
        if not s:
            return None
        parsed = parse_date(s)
        if parsed is None:
            raise HrChangeContextError("INVALID_REQUEST", f"无效日期: {s}")
        return parsed

    valid_scopes = {code for code, _ in ChangeScopeType.choices}
    if scope_type not in valid_scopes:
        raise HrChangeContextError("SCOPE_DENIED", f"非法数据范围: {scope_type}")

    return HrChangeRequestContext(
        tenant_id=tenant_id,
        school_timezone=school_timezone or DEFAULT_SCHOOL_TZ,
        user_id=user_id,
        as_of=_p(as_of),
        scope=HrChangeScope(scope_type=scope_type, org_id=scope_org_id),
    )


def resolve_tenant_from_request(request):
    """复用 hr_control_center.context.resolve_tenant_from_request。"""
    from hr_control_center.context import resolve_tenant_from_request as _resolve

    return _resolve(request)
