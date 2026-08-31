"""
hr_staff/context.py —— HR03 请求上下文（S1）。

硬合同（对齐总册 §1.2 A0 + HR01 context）：
- 无 tenant context → fail-closed（403 TENANT_CONTEXT_REQUIRED），不做全校兜底。
- “今天”按学校时区（school_timezone），禁止 date.today() 直用。
- scope 必须服务端重新验证，不信任前端参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date

from hr_staff.constants import StaffScopeType

DEFAULT_SCHOOL_TZ = "Asia/Shanghai"


class HrStaffContextError(Exception):
    """HR03 上下文错误（tenant/scope 解析失败）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class HrStaffScope:
    """HR03 数据范围（总册 6.2）。"""

    scope_type: str  # SCHOOL/COLLEGE/DEPARTMENT/ASSIGNMENT/SELF/EXPLICIT_STAFF_SET
    org_id: Optional[int] = None  # COLLEGE/DEPARTMENT 时组织 id
    staff_ids: frozenset = field(default_factory=frozenset)  # EXPLICIT_STAFF_SET
    label: str = ""

    @property
    def fingerprint(self) -> str:
        return f"hr03:{self.scope_type}:{self.org_id or ''}"


@dataclass(frozen=True)
class HrStaffRequestContext:
    tenant_id: Optional[int]
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    as_of: Optional[date] = None
    scope: HrStaffScope = field(default_factory=lambda: HrStaffScope(StaffScopeType.SCHOOL))
    request_snapshot_at: Optional[datetime] = None
    authority_mode: str = "LEGACY_STAFF_ONLY"

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


def build_staff_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    as_of: Optional[str] = None,
    scope_type: str = "SCHOOL",
    scope_org_id: Optional[int] = None,
    scope_staff_ids: Optional[list] = None,
    authority_mode: str = "LEGACY_STAFF_ONLY",
) -> HrStaffRequestContext:
    """从 HTTP 参数构造 HrStaffRequestContext（服务端必须重新验证 scope）。"""
    if not tenant_id:
        raise HrStaffContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

    def _p(s):
        if not s:
            return None
        parsed = parse_date(s)
        if parsed is None:
            raise HrStaffContextError("INVALID_REQUEST", f"无效日期: {s}")
        return parsed

    valid_scopes = {code for code, _ in StaffScopeType.choices}
    if scope_type not in valid_scopes:
        raise HrStaffContextError("SCOPE_NOT_ALLOWED", f"非法数据范围: {scope_type}")

    # P1-4：staff id 是 UUID，不得 int() 强转（静默失效 SELF/EXPLICIT_STAFF_SET）
    staff_ids = frozenset(x for x in (scope_staff_ids or []) if x and str(x).strip())

    return HrStaffRequestContext(
        tenant_id=tenant_id,
        school_timezone=school_timezone or DEFAULT_SCHOOL_TZ,
        user_id=user_id,
        as_of=_p(as_of),
        scope=HrStaffScope(
            scope_type=scope_type,
            org_id=scope_org_id,
            staff_ids=staff_ids,
        ),
        authority_mode=authority_mode,
    )


def resolve_tenant_from_request(request):
    """
    从当前请求解析学校租户。

    复用 hr_control_center.context.resolve_tenant_from_request
    （内部走 base.middleware.CompanyMiddleware 写入的 selected_company）。
    返回 int（学校 id）或 None（未明确学校上下文）。
    """
    from hr_control_center.context import resolve_tenant_from_request as _resolve

    return _resolve(request)
