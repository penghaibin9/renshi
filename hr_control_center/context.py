"""
hr_control_center/context.py

HrRequestContext —— 所有 HR01 指标/selector 共享的请求上下文。

硬合同（总册 18 / 22 节）：
- 所有“今天/本月/本年/90 天内”判断必须基于 school_timezone，禁止 date.today() 直用。
- 无学校上下文 → fail-closed（403 TENANT_CONTEXT_REQUIRED），不做 isnull=True 全校兜底。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date

DEFAULT_SCHOOL_TZ = "Asia/Shanghai"


class HrContextError(Exception):
    """HR01 上下文错误（tenant/scope 解析失败）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class HrScope:
    """
    ResolvedHrScope —— 聚合指标与 drilldown 必须共用同一 scope 合同。

    严禁：KPI 用全校数据，点进去列表只剩本学院。
    """

    scope_type: str  # SCHOOL / COLLEGE / DEPARTMENT / ASSIGNED
    org_id: Optional[int] = None  # COLLEGE/DEPARTMENT 时对应的组织 id
    label: str = ""

    @property
    def fingerprint(self) -> str:
        return f"{self.scope_type}:{self.org_id or ''}"


@dataclass(frozen=True)
class HrRequestContext:
    tenant_id: Optional[int]
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    as_of: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    scope: HrScope = field(default_factory=lambda: HrScope("SCHOOL"))
    request_snapshot_at: Optional[datetime] = None
    authority_mode: str = "LEGACY_ONLY"

    def __post_init__(self):
        if self.request_snapshot_at is None:
            object.__setattr__(
                self, "request_snapshot_at", dj_timezone.now()
            )
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
        """当前学校时区的今天。禁止任何 selector 直接使用 date.today()。"""
        local_now = self.request_snapshot_at.astimezone(self.tzinfo())
        return local_now.date()

    def now(self) -> datetime:
        return datetime.now(timezone.utc).astimezone(self.tzinfo())

    def tzinfo(self):
        try:
            import zoneinfo

            return zoneinfo.ZoneInfo(self.school_timezone)
        except Exception:
            from zoneinfo import ZoneInfo

            return ZoneInfo(DEFAULT_SCHOOL_TZ)

    def scope_fingerprint(self) -> str:
        return self.scope.fingerprint


def build_hr_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    as_of: Optional[str] = None,
    period_from: Optional[str] = None,
    period_to: Optional[str] = None,
    scope_type: str = "SCHOOL",
    scope_org_id: Optional[int] = None,
    authority_mode: str = "LEGACY_ONLY",
) -> HrRequestContext:
    """从 HTTP 参数构造 HrRequestContext（服务端必须重新验证 scope，不能信任前端参数）。"""
    if not tenant_id:
        raise HrContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

    def _p(s):
        if not s:
            return None
        parsed = parse_date(s)
        if parsed is None:
            raise HrContextError("INVALID_REQUEST", f"无效日期: {s}")
        return parsed

    scope_types = {"SCHOOL", "COLLEGE", "DEPARTMENT", "ASSIGNED"}
    if scope_type not in scope_types:
        raise HrContextError("SCOPE_NOT_ALLOWED", f"非法数据范围: {scope_type}")

    return HrRequestContext(
        tenant_id=tenant_id,
        school_timezone=school_timezone or DEFAULT_SCHOOL_TZ,
        user_id=user_id,
        as_of=_p(as_of),
        period_from=_p(period_from),
        period_to=_p(period_to),
        scope=HrScope(scope_type=scope_type, org_id=scope_org_id),
        authority_mode=authority_mode,
    )


def resolve_tenant_from_request(request):
    """
    从当前请求解析学校租户。

    复用 base.middleware.CompanyMiddleware 已写入的 selected_company。
    返回:
      - int: 学校 id（当前选择的具体学校）
      - "all": 用户选择“全部学校”——HR01 指标在此语义下仍须 fail-closed
                （聚合指标不能跨校合并出一个无意义数字），由调用方决定。
    """
    from horilla.horilla_middlewares import get_selected_company

    company_id = get_selected_company()
    if company_id in (None, "all", ""):
        return None
    try:
        return int(company_id)
    except (TypeError, ValueError):
        return None
