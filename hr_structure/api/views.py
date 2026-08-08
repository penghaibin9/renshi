"""
hr_structure/api/views.py

HR02 API（总册 25 / 39 节）。统一 /api/hr/v1/structure/* 前缀。
root 含 apiVersion/schemaVersion/requestId/tenantId/asOf/dataBasis。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from hr_control_center.context import (
    HrContextError,
    resolve_tenant_from_request,
)
from hr_structure.scope import Hr02Scope, resolve_scope
from hr_structure.selectors.organization import OrganizationSelector

logger = logging.getLogger(__name__)

API_VERSION = "1.0"
SCHEMA_VERSION = "hr02-1.0"


def _request_id(request) -> str:
    rid = getattr(request, "hr02_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr02_request_id = rid
    return rid


def _root(request, tenant_id, as_of, **extra) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "tenantId": str(tenant_id),
        "asOf": as_of.isoformat() if hasattr(as_of, "isoformat") else as_of,
        "dataBasis": "HR02_AUTHORITY",
        **extra,
    }


def _json(request, payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _error(request, code, message, status=422, details=None):
    return _json(
        request,
        {
            "apiVersion": API_VERSION,
            "requestId": _request_id(request),
            "error": {"code": code, "message": message, "details": details, "retryable": False},
        },
        status=status,
    )


def _parse_as_of(request):
    raw = request.GET.get("asOf")
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HrContextError("HR02_INVALID_ASOF", "无效日期")


def _make_scope(request) -> Hr02Scope:
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrContextError("HR02_TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    return resolve_scope(
        tenant_id,
        scope_type=request.GET.get("scope_type", "SCHOOL"),
        org_id=request.GET.get("scope_id"),
    )


@require_GET
def organizations_bootstrap(request):
    """GET /api/hr/v1/structure/organizations/bootstrap"""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    selector = OrganizationSelector(scope, as_of=as_of)
    root = selector.get_root()
    payload = _root(
        request, scope.tenant_id, as_of,
        permissions={
            "canCreate": True,
            "canSubmitChange": True,
            "canViewHistory": True,
        },
        root={
            "id": root.organization_id_id if root else None,
            "code": root.organization_id.stable_code if root else None,
            "name": root.name if root else None,
            "org_type": root.org_type if root else None,
            "childCount": root.child_versions.count() if root else 0,
        },
        summary={
            "activeOrganizations": 0,
            "futureChanges": 0,
            "dataQualityIssues": 0,
        },
    )
    return _json(request, payload)


@require_GET
def organizations_tree(request):
    """GET /api/hr/v1/structure/organizations/tree?parent_id=...&asOf=..."""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    parent_id = request.GET.get("parent_id")
    if not parent_id:
        return _error(request, "HR02_ORG_NOT_FOUND", "缺少 parent_id")

    selector = OrganizationSelector(scope, as_of=as_of)
    children = selector.get_children(int(parent_id))
    nodes = [
        {
            "id": v.organization_id_id,
            "stable_code": v.organization_id.stable_code,
            "name": v.name,
            "org_type": v.org_type,
            "has_children": v.child_versions.exists(),
            "validity_from": v.validity_from.isoformat(),
        }
        for v in children
    ]
    return _json(request, _root(request, scope.tenant_id, as_of, nodes=nodes))


@require_GET
def organization_detail(request, org_id):
    """GET /api/hr/v1/structure/organizations/{id}?asOf=..."""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    selector = OrganizationSelector(scope, as_of=as_of)
    org = selector.get_organization(int(org_id))
    if org is None:
        return _error(request, "HR02_ORG_NOT_FOUND", "组织不存在", status=404)
    version = selector.get_version_as_of(int(org_id))
    child_count = selector.get_children(int(org_id)).count()
    return _json(
        request,
        _root(
            request, scope.tenant_id, as_of,
            id=org.id,
            stable_code=org.stable_code,
            name=version.name if version else org.stable_code,
            org_type=version.org_type if version else None,
            status=version.status if version else None,
            validity_from=version.validity_from.isoformat() if version else None,
            validity_to=version.validity_to.isoformat() if version and version.validity_to else None,
            child_count=child_count,
        ),
    )


# ---------------------------------------------------------------------------
# 组织变更（总册 9.8 / 39.2）—— 写操作
# ---------------------------------------------------------------------------


def organization_changes(request):
    """POST /api/hr/v1/structure/organization-changes —— 创建组织变更 case。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.organization.change.submit")):
        return _error(request, "HR02_SCOPE_DENIED", "无发起组织变更权限", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    change_type = body.get("changeType")
    title = body.get("title", "")
    reason = body.get("reason", "")
    effective = body.get("effectiveDate")
    if not change_type or not effective:
        return _error(request, "HR02_INVALID_REQUEST", "缺少 changeType/effectiveDate", status=400)
    try:
        from datetime import date as _date

        effective_date = _date.fromisoformat(effective)
    except ValueError:
        return _error(request, "HR02_INVALID_REQUEST", "无效生效日期", status=400)

    try:
        from hr_structure.services.organization_change import OrganizationChangeService

        svc = OrganizationChangeService(scope, actor=str(getattr(request.user, "id", "")))
        case = svc.create_change_case(
            change_type=change_type,
            title=title,
            reason=reason,
            requested_effective_date=effective_date,
            items=body.get("items", []),
        )
    except Hr02ServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)

    return _json(
        request,
        _root(
            request, scope.tenant_id, date.today(),
            case={"id": case.id, "caseNo": case.case_no, "status": case.status},
        ),
        status=201,
    )


# ---------------------------------------------------------------------------
# 岗位预占（总册 50.1）—— 预占 / 提交 / 释放 / 列表 / 可用性
# 供 HR04 招聘、HR05 入职、HR06 调动、HR14 聘任调用。
# ---------------------------------------------------------------------------


def position_reservations(request):
    """POST /api/hr/v1/structure/position-reservations —— 创建预占（并发防超卖）。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.position.manage")):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位管理权限", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    idempotency_key = request.headers.get("Idempotency-Key") or body.get("idempotencyKey")
    if not idempotency_key:
        return _error(request, "HR02_INVALID_REQUEST", "缺少 Idempotency-Key", status=400)

    try:
        from hr_structure.services.position import PositionService, PositionServiceError

        svc = PositionService(scope, actor=str(getattr(request.user, "id", "")))
        r = svc.reserve(
            source_domain=body.get("sourceDomain", ""),
            source_business_type=body.get("sourceBusinessType", ""),
            source_business_id=body.get("sourceBusinessId", ""),
            position_id=body.get("positionId"),
            position_pool_id=body.get("positionPoolId"),
            count=int(body.get("count", 1)),
            fte=float(body.get("fte", 1.0)),
            idempotency_key=idempotency_key,
        )
    except PositionServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)
    except (TypeError, ValueError):
        return _error(request, "HR02_INVALID_REQUEST", "count/fte 参数无效", status=400)

    return _json(
        request,
        _root(
            request, scope.tenant_id, date.today(),
            reservation={
                "id": r.id,
                "reservationNo": r.reservation_no,
                "status": r.status,
                "sourceBusinessId": r.source_business_id,
            },
        ),
        status=201,
    )


def position_reservation_action(request, reservation_id, action):
    """POST /api/hr/v1/structure/position-reservations/{id}/commit|release"""
    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.position.manage")):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位管理权限", status=403)

    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        from hr_structure.services.position import PositionService, PositionServiceError

        svc = PositionService(scope, actor=str(getattr(request.user, "id", "")))
        if action == "commit":
            r = svc.commit(reservation_id)
        elif action == "release":
            r = svc.release(reservation_id)
        else:
            return _error(request, "HR02_INVALID_REQUEST", "未知动作", status=400)
    except PositionServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)

    return _json(
        request,
        _root(
            request, scope.tenant_id, date.today(),
            reservation={"id": r.id, "reservationNo": r.reservation_no, "status": r.status},
        ),
    )


@require_GET
def position_reservations_list(request):
    """GET /api/hr/v1/structure/position-reservations?sourceBusinessId=..."""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrPositionReservation

    qs = HrPositionReservation.objects.filter(tenant_id=scope.tenant_id)
    source_id = request.GET.get("sourceBusinessId")
    if source_id:
        qs = qs.filter(source_business_id=source_id)
    items = [
        {
            "id": r.id,
            "reservationNo": r.reservation_no,
            "status": r.status,
            "sourceBusinessId": r.source_business_id,
            "positionId": r.position_id_id,
            "positionPoolId": r.position_pool_id_id,
            "reservedCount": r.reserved_count,
        }
        for r in qs.order_by("-id")[:100]
    ]
    return _json(request, _root(request, scope.tenant_id, date.today(), items=items))


@require_GET
def position_availability(request):
    """GET /api/hr/v1/structure/position-control/availability?positionId=..."""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.selectors.position import PositionSelector

    selector = PositionSelector(scope, as_of=as_of)
    result = selector.availability(
        position_id=request.GET.get("positionId"),
        post_catalog_version_id=request.GET.get("postCatalogId"),
        organization_id=request.GET.get("organizationId"),
    )
    return _json(request, _root(request, scope.tenant_id, as_of, **result))
