"""
hr_assessment/context.py —— HR12 请求上下文（生产级）。

硬合同：
- 无 tenant context → fail-closed（403 TENANT_CONTEXT_REQUIRED）
- "今天"按学校时区
- scope 必须服务端重新验证
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date

from hr_assessment.constants import DataScope

DEFAULT_SCHOOL_TZ = "Asia/Shanghai"


class HrAssessmentContextError(Exception):
    def __init__(self, code: str, message: str, status: int = 403):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class HrAssessmentScope:
    scope_type: str = DataScope.SCHOOL.value
    org_id: Optional[int] = None
    staff_ids: frozenset = field(default_factory=frozenset)
    label: str = ""


@dataclass(frozen=True)
class HrAssessmentRequestContext:
    tenant_id: int
    school_timezone: str = DEFAULT_SCHOOL_TZ
    user_id: Optional[int] = None
    as_of: Optional[date] = None
    scope: HrAssessmentScope = field(default_factory=lambda: HrAssessmentScope(DataScope.SCHOOL.value))
    request_snapshot_at: Optional[datetime] = None

    def __post_init__(self):
        if self.request_snapshot_at is None:
            object.__setattr__(self, "request_snapshot_at", dj_timezone.now())
        if self.as_of is None:
            object.__setattr__(self, "as_of", self.today())
        if not self.tenant_id:
            raise HrAssessmentContextError("TENANT_CONTEXT_REQUIRED", "缺少学校上下文")

    def today(self) -> date:
        local_now = self.request_snapshot_at.astimezone(self.tzinfo())
        return local_now.date()

    def tzinfo(self):
        import zoneinfo
        return zoneinfo.ZoneInfo(self.school_timezone)


def resolve_tenant_from_assignment(request) -> Optional[int]:
    """从请求解析租户——复用 CompanyMiddleware 的 selected_company。"""
    from hr_control_center.context import resolve_tenant_from_request
    return resolve_tenant_from_request(request)


def resolve_authenticated_staff_id(request, tenant_id: int, *, required: bool = False):
    """Resolve the authenticated account to exactly one tenant-scoped HR03 staff.

    Canonical account links take precedence. Legacy Employee linkage is only a
    compatibility bridge and is still resolved through the HR03 master. Ambiguous
    active mappings fail closed instead of choosing an arbitrary staff record.
    """

    user = getattr(request, "user", None)
    user_id = getattr(user, "id", None)
    if user_id:
        from hr_staff.models import HrAccountLink

        linked_ids = list(
            HrAccountLink.objects.filter(
                tenant_id=tenant_id,
                auth_user_id=user_id,
                link_status=HrAccountLink.LinkStatus.ACTIVE,
            )
            .order_by("staff_id_id")
            .values_list("staff_id_id", flat=True)[:2]
        )
        if len(linked_ids) > 1:
            raise HrAssessmentContextError(
                "SELF_STAFF_MAPPING_AMBIGUOUS",
                "当前账号在本学校关联了多个有效教职工主档，请先修复账号映射。",
            )
        if linked_ids:
            return linked_ids[0]

    employee = getattr(user, "employee_get", None)
    try:
        if callable(employee):
            employee = employee()
    except Exception:
        employee = None
    legacy_employee_id = getattr(employee, "id", None)
    if legacy_employee_id:
        from hr_staff.models import HrStaffMaster

        staff_ids = list(
            HrStaffMaster.objects.filter(
                tenant_id=tenant_id,
                legacy_employee_id=legacy_employee_id,
            )
            .order_by("id")
            .values_list("id", flat=True)[:2]
        )
        if len(staff_ids) > 1:
            raise HrAssessmentContextError(
                "SELF_STAFF_MAPPING_AMBIGUOUS",
                "当前账号的历史人员映射不唯一，请先修复教职工主档。",
            )
        if staff_ids:
            return staff_ids[0]

    if required:
        raise HrAssessmentContextError(
            "SELF_STAFF_MAPPING_REQUIRED",
            "当前账号在本学校尚未关联 HR03 教职工主档。",
        )
    return None


def build_assessment_context(
    *,
    tenant_id: Optional[int],
    school_timezone: str = DEFAULT_SCHOOL_TZ,
    user_id: Optional[int] = None,
    as_of: Optional[str] = None,
    scope_type: str = "SCHOOL",
    scope_org_id: Optional[int] = None,
    scope_staff_ids: Optional[list] = None,
) -> HrAssessmentRequestContext:
    if not tenant_id:
        raise HrAssessmentContextError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    valid_scopes = {code for code, _ in DataScope.choices}
    if scope_type not in valid_scopes:
        raise HrAssessmentContextError("SCOPE_NOT_ALLOWED", f"非法数据范围: {scope_type}")
    parsed_date = None
    if as_of:
        parsed_date = parse_date(as_of)
        if parsed_date is None:
            raise HrAssessmentContextError("INVALID_REQUEST", f"无效日期: {as_of}")

    staff_ids = frozenset(str(x) for x in (scope_staff_ids or []) if x)
    return HrAssessmentRequestContext(
        tenant_id=tenant_id,
        school_timezone=school_timezone or DEFAULT_SCHOOL_TZ,
        user_id=user_id,
        as_of=parsed_date,
        scope=HrAssessmentScope(
            scope_type=scope_type,
            org_id=scope_org_id,
            staff_ids=staff_ids,
        ),
    )
