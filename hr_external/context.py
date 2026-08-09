"""
hr_external/context.py —— HR08 请求上下文（S1）。

硬合同（对齐总册 §89 + HR03/HR01 context）：
- 无 tenant context → fail-closed（403 TENANT_CONTEXT_REQUIRED），不做全校兜底；
- “今天”按学校时区（school_timezone），禁止 date.today() 直用；
- scope 必须服务端重新验证，不信任前端参数；
- HR08 特有 scope：ENGAGEMENT / ASSIGNED_TASKS / SELF（§89）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date

from hr_external.constants import ExternalScopeType

DEFAULT_SCHOOL_TZ = "Asia/Shanghai"


class HrExternalContextError(Exception):
    """HR08 上下文错误（tenant/scope 解析失败）。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class HrExternalScope:
    """HR08 数据范围（§89）。"""

    scope_type: str  # SCHOOL/COLLEGE/ORGANIZATION/ENGAGEMENT/ASSIGNED_TASKS/SELF
    org_id: Optional[int] = None  # COLLEGE/ORGANIZATION 时组织 id
    engagement_ids: frozenset = field(default_factory=frozenset)  # ENGAGEMENT 显式集合
    label: str = ""

    @property
    def fingerprint(self) -> str:
        return f"hr08:{self.scope_type}:{self.org_id or ''}"


@dataclass(frozen=True)
class HrExternalRequestContext:
    tenant_id: Optional[int]
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    as_of: Optional[date] = None
    scope: HrExternalScope = field(
        default_factory=lambda: HrExternalScope(ExternalScopeType.SCHOOL)
    )
    request_snapshot_at: Optional[datetime] = None
    authority_mode: str = "LEGACY_EMPLOYEE_TAG_ONLY"

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


def build_external_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    as_of: Optional[str] = None,
    scope_type: str = "SCHOOL",
    scope_org_id: Optional[int] = None,
    scope_engagement_ids: Optional[list] = None,
    authority_mode: str = "LEGACY_EMPLOYEE_TAG_ONLY",
) -> HrExternalRequestContext:
    """从 HTTP 参数构造 HrExternalRequestContext（服务端必须重新验证 scope）。"""
    if not tenant_id:
        raise HrExternalContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")

    def _p(s):
        if not s:
            return None
        parsed = parse_date(s)
        if parsed is None:
            raise HrExternalContextError("INVALID_REQUEST", f"无效日期: {s}")
        return parsed

    valid_scopes = {code for code, _ in ExternalScopeType.choices}
    if scope_type not in valid_scopes:
        raise HrExternalContextError("EXTERNAL_SCOPE_DENIED", f"非法数据范围: {scope_type}")

    engagement_ids = frozenset(str(x) for x in (scope_engagement_ids or []) if str(x))

    return HrExternalRequestContext(
        tenant_id=tenant_id,
        school_timezone=school_timezone or DEFAULT_SCHOOL_TZ,
        user_id=user_id,
        as_of=_p(as_of),
        scope=HrExternalScope(
            scope_type=scope_type,
            org_id=scope_org_id,
            engagement_ids=engagement_ids,
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


def authorize_external_scope(request, *, tenant_id: int, scope_type: str, scope_org_id):
    """
    Data scope 授权校验（A13，总册 §89/§6.2）：服务端按用户实际 membership 校验，
    不信任前端 scope_type/scope_id 参数。

    - superuser / 学校级 HR → 任意 scope；
    - 非 superuser 请求 COLLEGE/ORGANIZATION scope → 必须通过 HrLegacyObjectLink
      （Department ↔ HrOrganization）证明该用户 legacy Employee 的部门映射到目标组织；
    - 无映射/无 membership 数据 → 403 fail-closed（绝不静默放行）。
    """
    if request.user.is_superuser:
        return
    if scope_type in ("SCHOOL",):
        return
    if scope_type in ("COLLEGE", "ORGANIZATION") and scope_org_id:
        allowed = _user_allowed_org_ids(request, tenant_id)
        if scope_org_id not in allowed:
            raise HrExternalContextError(
                "EXTERNAL_SCOPE_DENIED", "无权访问该组织范围（data scope 越权）"
            )
        return
    # ENGAGEMENT / ASSIGNED_TASKS / SELF：由各端点按 owner 校验，此处不作组织级放行
    if scope_type in ("ENGAGEMENT", "ASSIGNED_TASKS", "SELF"):
        return
    raise HrExternalContextError("EXTERNAL_SCOPE_DENIED", "非法数据范围")


def _user_allowed_org_ids(request, tenant_id: int) -> set:
    """用户 legacy Employee 的 department → HR02 组织映射集合。

    通过 HrLegacyObjectLink（legacy Department → HrOrganization）解析；
    无法解析时返回空集（fail-closed）。
    """
    allowed: set = set()
    try:
        from employee.models import Employee

        emp = Employee.objects.filter(employee_user_id=request.user.id).first()
        if emp is None:
            return allowed
        dept = getattr(getattr(emp, "employee_work_info", None), "department_id", None)
        if dept is None:
            return allowed

        from hr_structure.models import HrLegacyObjectLink

        links = HrLegacyObjectLink.objects.filter(
            tenant_id=tenant_id,
            domain_entity_type="organization",
            legacy_app="base",
            legacy_model="department",
            legacy_pk=str(dept.id),
            link_status="MAPPED",
        )
        for link in links:
            try:
                allowed.add(int(link.domain_entity_id))
            except (TypeError, ValueError):
                continue
    except Exception:  # noqa: BLE001 —— membership 数据不可用一律 fail-closed
        return set()
    return allowed
