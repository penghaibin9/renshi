"""
hr_onboarding/context.py

Hr05RequestContext —— HR05 所有 selector/service/api 共享的请求上下文。

硬合同（05 §1 A0 继承 + HR01 context 继承）：
- tenant/school 由服务端可信上下文解析，禁止信任前端 tenant_id。
- 无学校上下文 → fail-closed（403 TENANT_CONTEXT_REQUIRED），不做 isnull=True 全校兜底。
- 所有"今天/预计/到期"判断基于 school_timezone，禁止 date.today() 直用。
- authority_mode 显式：LEGACY_ONBOARDING_ONLY / DUAL_READ_COMPARE / HR05_AUTHORITY。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from django.utils import timezone as dj_timezone

from hr_control_center.context import (
    DEFAULT_SCHOOL_TZ,
    HrContextError,
    HrScope,
    build_hr_context,
    resolve_tenant_from_request,
)

# 复用 HR01 上下文错误（TENANT_CONTEXT_REQUIRED / SCOPE_NOT_ALLOWED 等）
__all__ = [
    "Hr05RequestContext",
    "HrContextError",
    "build_hr05_context",
    "resolve_tenant_from_request",
    "HrScope",
]


@dataclass(frozen=True)
class Hr05RequestContext:
    """
    HR05 请求上下文（冻结）。

    字段与 HR01 HrRequestContext 对齐，另加 authority_mode 默认
    LEGACY_ONBOARDING_ONLY（Authority 切换前）。
    """

    tenant_id: Optional[int]
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    as_of: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    scope: HrScope = HrScope("SCHOOL")
    request_snapshot_at: Optional[datetime] = None
    authority_mode: str = "LEGACY_ONBOARDING_ONLY"

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
        """当前学校时区的今天。禁止直接使用 date.today()。"""
        return self.request_snapshot_at.astimezone(self.tzinfo()).date()

    def now(self) -> datetime:
        return self.request_snapshot_at.astimezone(self.tzinfo())

    def tzinfo(self):
        try:
            import zoneinfo

            return zoneinfo.ZoneInfo(self.school_timezone)
        except Exception:
            from zoneinfo import ZoneInfo

            return ZoneInfo(DEFAULT_SCHOOL_TZ)

    def scope_fingerprint(self) -> str:
        return f"{self.scope.scope_type}:{self.scope.org_id or ''}"


def build_hr05_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    as_of: Optional[str] = None,
    period_from: Optional[str] = None,
    period_to: Optional[str] = None,
    scope_type: str = "SCHOOL",
    scope_org_id: Optional[int] = None,
    authority_mode: str = "LEGACY_ONBOARDING_ONLY",
) -> Hr05RequestContext:
    """从请求参数构造 Hr05RequestContext（服务端必须重新验证 scope，不信任前端参数）。"""
    inner = build_hr_context(
        tenant_id=tenant_id,
        school_timezone=school_timezone,
        user_id=user_id,
        as_of=as_of,
        period_from=period_from,
        period_to=period_to,
        scope_type=scope_type,
        scope_org_id=scope_org_id,
        authority_mode=authority_mode,
    )
    return Hr05RequestContext(
        tenant_id=inner.tenant_id,
        school_timezone=inner.school_timezone,
        user_id=inner.user_id,
        as_of=inner.as_of,
        period_from=inner.period_from,
        period_to=inner.period_to,
        scope=inner.scope,
        request_snapshot_at=inner.request_snapshot_at,
        authority_mode=inner.authority_mode,
    )
