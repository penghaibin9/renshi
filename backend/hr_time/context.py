"""
hr_time/context.py

HrTimeContext —— HR11 所有 API/服务共享的请求上下文（fail-closed）。

硬合同（总册 §142/§144/§25）：
- 所有“今天/本月/今年”判断必须基于学校时区（school_timezone），禁止 date.today() 直用；
- 无学校上下文 → fail-closed（403 TENANT_CONTEXT_REQUIRED），不做全校兜底；
- as-of 查询必须携带当时的 tenant/policy/calendar/schedule 引用，今天调岗不能改变去年缺勤结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date

DEFAULT_SCHOOL_TZ = "Asia/Shanghai"


class HrTimeContextError(Exception):
    """HR11 上下文错误（tenant/scope 解析失败）。"""

    def __init__(self, code: str, message: str, status: int = 403):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class HrTimeScope:
    """数据范围（总册 §152）：跨校永不自动开放。"""

    scope_type: str  # SELF / DIRECT_REPORTS / ORG_SUBTREE / ASSIGNED_ORGS / LOCATION / TENANT_ALL / AUDIT_READONLY
    org_id: Optional[int] = None
    label: str = ""

    @property
    def fingerprint(self) -> str:
        return f"{self.scope_type}:{self.org_id or ''}"


@dataclass(frozen=True)
class HrTimeContext:
    tenant_id: Optional[int]
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    actor_employee_id: Optional[int] = None
    as_of: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    scope: HrTimeScope = field(default_factory=lambda: HrTimeScope("TENANT_ALL"))
    request_snapshot_at: Optional[datetime] = None
    authority_mode: str = "LEGACY_ONLY"

    def __post_init__(self):
        if self.request_snapshot_at is None:
            object.__setattr__(self, "request_snapshot_at", dj_timezone.now())
        if self.as_of is None:
            object.__setattr__(self, "as_of", self.today())
        if self.period_to is None:
            object.__setattr__(self, "period_to", self.as_of)
        if self.period_from is None:
            from datetime import timedelta

            object.__setattr__(
                self,
                "period_from",
                self.as_of.replace(day=1),
            )

    def today(self) -> date:
        """当前学校时区的今天。禁止任何 HR11 selector 直接使用 date.today()。"""
        local_now = self.request_snapshot_at.astimezone(self.tzinfo())
        return local_now.date()

    def now(self) -> datetime:
        return datetime.now(timezone.utc).astimezone(self.tzinfo())

    def tzinfo(self):
        import zoneinfo

        try:
            return zoneinfo.ZoneInfo(self.school_timezone)
        except Exception:
            return zoneinfo.ZoneInfo(DEFAULT_SCHOOL_TZ)

    def scope_fingerprint(self) -> str:
        return self.scope.fingerprint


def resolve_tenant_from_request(request):
    """
    从当前请求解析学校租户（复用 CompanyMiddleware 写入的 selected_company）。

    fail-closed：没有明确具体学校时返回 None（"all"/缺失/非法值一律视为无上下文），
    由调用方拒绝请求，绝不回退到 isnull=True 全校数据。
    """
    from horilla.horilla_middlewares import get_selected_company

    company_id = get_selected_company()
    if company_id in (None, "all", ""):
        return None
    try:
        return int(company_id)
    except (TypeError, ValueError):
        return None

def build_hr_time_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    actor_employee_id: Optional[int] = None,
    as_of: Optional[str] = None,
    period_from: Optional[str] = None,
    period_to: Optional[str] = None,
    scope_type: str = "TENANT_ALL",
    scope_org_id: Optional[int] = None,
    authority_mode: str = "LEGACY_ONLY",
) -> HrTimeContext:
    """从 HTTP 参数构造 HrTimeContext。tenant 缺失/非法直接抛 HrTimeContextError。"""
    if not tenant_id:
        raise HrTimeContextError(
            "TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）"
        )

    def _p(s):
        if not s:
            return None
        parsed = parse_date(s)
        if parsed is None:
            raise HrTimeContextError("INVALID_REQUEST", f"无效日期: {s}")
        return parsed

    from hr_time.constants import ALL_TIME_DATA_SCOPES

    if scope_type not in ALL_TIME_DATA_SCOPES:
        raise HrTimeContextError("INVALID_REQUEST", f"非法数据范围: {scope_type}")

    return HrTimeContext(
        tenant_id=int(tenant_id),
        school_timezone=school_timezone or DEFAULT_SCHOOL_TZ,
        user_id=user_id,
        actor_employee_id=actor_employee_id,
        as_of=_p(as_of),
        period_from=_p(period_from),
        period_to=_p(period_to),
        scope=HrTimeScope(scope_type=scope_type, org_id=scope_org_id),
        authority_mode=authority_mode,
    )
