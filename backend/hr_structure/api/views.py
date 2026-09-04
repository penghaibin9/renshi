"""
hr_structure/api/views.py

HR02 API（总册 25 / 39 节）。统一 /api/hr/v1/structure/* 前缀。
root 含 apiVersion/schemaVersion/requestId/tenantId/asOf/dataBasis。
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from hr_control_center.context import (
    HrContextError,
    resolve_tenant_from_request,
)

from hr_structure.display_labels import (
    AUTHORITY_MODE,
    CHANGE_CASE_STATUS,
    CHANGE_TYPE,
    DATA_BASIS,
    METRIC_FRESHNESS,
    ORG_RELATION_STATUS,
    ORG_RELATION_TYPE,
    ORG_TYPE,
    ORG_VERSION_STATUS,
    POSITION_LIFECYCLE_STATUS,
    POSITION_OCCUPANCY_STATUS,
    POSITION_RESERVATION_STATUS,
    POST_CATALOG_CATEGORY,
    POST_CATALOG_CONTROL_MODE,
    POST_CATALOG_SUBCATEGORY,
    SCOPE_TYPE,
    STAFFING_PLAN_STATUS,
    append_labels,
    append_labels_deep,
    label_of,
)
from hr_structure.permissions import has_hr02_permission
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
    """构建 API 根信封。自动为已知枚举字段追加 *Label（总控 §12）。"""
    # 标签注入：遍历 extra 中已知枚举字段名，自动追加 fieldLabel
    _LABEL_MAP = {
        "org_type": ORG_TYPE,
        "status": ORG_VERSION_STATUS,
        "lifecycleStatus": POSITION_LIFECYCLE_STATUS,
        "occupancyStatus": POSITION_OCCUPANCY_STATUS,
        "changeType": CHANGE_TYPE,
        "category": POST_CATALOG_CATEGORY,
        "subcategory": POST_CATALOG_SUBCATEGORY,
        "controlMode": POST_CATALOG_CONTROL_MODE,
        "mode": AUTHORITY_MODE,
        "relationType": ORG_RELATION_TYPE,
    }
    for field, mapping in _LABEL_MAP.items():
        val = extra.get(field)
        if val is not None:
            extra[f"{field}Label"] = label_of(mapping, val)
    # 特殊：status 字段在不同上下文有不同含义（ORG_VERSION_STATUS 是默认，
    # 但 POSITION_RESERVATION_STATUS / STAFFING_PLAN_STATUS / CHANGE_CASE_STATUS
    # 也可以在调用方显式传 statusLabel 覆盖）
    if extra.get("status") is not None and "statusLabel" not in extra:
        extra["statusLabel"] = label_of(ORG_VERSION_STATUS, extra["status"])

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
        return timezone.localdate()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HrContextError("HR02_INVALID_ASOF", "无效日期")


# ---- 标签注入（总控 §12：成对 {field, fieldLabel}）----

def _inject_labels(data: dict, *, field_specs: list):
    """
    给 dict 自动追加 *Label。field_specs: [(field_name, label_mapping), ...]
    例: _inject_labels(d, field_specs=[("org_type", ORG_TYPE), ("status", ORG_VERSION_STATUS)])
    """
    for field_name, mapping in field_specs:
        value = data.get(field_name)
        if value is not None:
            data[f"{field_name}Label"] = label_of(mapping, value)


def _inject_labels_list(items: list, *, field_specs: list):
    for item in items:
        _inject_labels(item, field_specs=field_specs)


def _make_scope(request) -> Hr02Scope:
    """服务端解析 scope：认证 + tenant + 用户授权范围（总册 35.1，不信前端任意值）。"""
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        raise HrContextError("HR02_SCOPE_DENIED", "请先登录")
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrContextError("HR02_TENANT_CONTEXT_REQUIRED", "请选择当前学校")

    # selected_company 只是会话里的当前选择，不是租户授权凭据。非平台超级
    # 管理员必须被明确分配到当前学校；空集合表示没有任何学校权限，不能被
    # 当作“未配置限制/全校可见”。这里是 HR02 所有 canonical 读写入口共用
    # 的 scope 构造器，因此在业务 service 取数或写库之前统一 fail-closed。
    if not getattr(user, "is_superuser", False):
        from base.auth_backends import get_allowed_company_ids

        allowed = get_allowed_company_ids(user)
        if tenant_id not in (allowed or ()):
            raise HrContextError(
                "HR02_TENANT_CONTEXT_REQUIRED", "当前账号无权访问该学校数据"
            )

    # scope_type 白名单由 resolve_scope 校验；scope_id 仅当用户是 superuser 或拥有组织权限时接受
    scope_type = request.GET.get("scope_type", "SCHOOL")
    if scope_type != "SCHOOL" and not has_hr02_permission(
        user, "hr.structure.organization.view"
    ):
        raise HrContextError("HR02_SCOPE_DENIED", "无该数据范围权限")
    return resolve_scope(
        tenant_id,
        scope_type=scope_type,
        org_id=request.GET.get("scope_id"),
    )


@require_GET
def organizations_bootstrap(request):
    """GET /api/hr/v1/structure/organizations/bootstrap"""
    if not has_hr02_permission(request.user, "hr.structure.organization.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织查看权限", status=403)
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
            "canCreate": has_hr02_permission(request.user, "hr.structure.organization.create"),
            "canSubmitChange": has_hr02_permission(request.user, "hr.structure.organization.change.submit"),
            "canViewHistory": has_hr02_permission(request.user, "hr.structure.organization.history.view"),
        },
        root={
            "id": root.organization_id_id if root else None,
            "code": root.organization_id.stable_code if root else None,
            "name": root.name if root else None,
            "org_type": root.org_type if root else None,
            "childCount": (
                selector.get_children(root.organization_id_id).count() if root else 0
            ),
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
    if not has_hr02_permission(request.user, "hr.structure.organization.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织查看权限", status=403)
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
    child_ids = [c.organization_id_id for c in children]
    # 批量查孙级：哪些子节点有下级（避免每节点 exists() 的 N+1，也避免恒真 bug）
    from hr_structure.models import HrOrganizationVersion

    grandchild_org_ids = set(
        HrOrganizationVersion.objects.filter(
            tenant_id=scope.tenant_id,
            status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
            parent_organization_id__in=child_ids,
            validity_from__lte=as_of,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
        .values_list("parent_organization_id", flat=True)
    )
    nodes = [
        {
            "id": v.organization_id_id,
            "stable_code": v.organization_id.stable_code,
            "name": v.name,
            "org_type": v.org_type,
            "has_children": v.organization_id_id in grandchild_org_ids,
            "validity_from": v.validity_from.isoformat(),
        }
        for v in children
    ]
    append_labels_deep(nodes, field_mappings=[("org_type", ORG_TYPE)])
    return _json(request, _root(request, scope.tenant_id, as_of, nodes=nodes))


@require_GET
def organization_options(request):
    """供业务表单选择机构；按生效日期返回有限、租户隔离的轻量选项。"""
    if not has_hr02_permission(request.user, "hr.structure.organization.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织查看权限", status=403)
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
        limit = int(request.GET.get("limit", 200) or 200)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except (TypeError, ValueError):
        return _error(request, "HR02_INVALID_REQUEST", "选项数量必须是整数", status=400)
    limit = min(max(limit, 1), 500)
    versions = OrganizationSelector(scope, as_of=as_of).search(
        str(request.GET.get("q", "")).strip(), limit=limit
    )
    items = [
        {
            "id": version.organization_id_id,
            "code": version.organization_id.stable_code,
            "name": version.name,
            "orgType": version.org_type,
        }
        for version in versions
    ]
    return _json(request, _root(request, scope.tenant_id, as_of, items=items))


@require_GET
def organization_detail(request, org_id):
    """GET /api/hr/v1/structure/organizations/{id}?asOf=..."""
    if not has_hr02_permission(request.user, "hr.structure.organization.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织查看权限", status=403)
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
    payload = _root(
            request, scope.tenant_id, as_of,
            id=org.id,
            stable_code=org.stable_code,
            name=version.name if version else org.stable_code,
            org_type=version.org_type if version else None,
            status=version.status if version else None,
            validity_from=version.validity_from.isoformat() if version else None,
            validity_to=version.validity_to.isoformat() if version and version.validity_to else None,
            child_count=child_count,
        )
    _inject_labels(
        payload,
        field_specs=[("org_type", ORG_TYPE), ("status", ORG_VERSION_STATUS)],
    )
    return _json(request, payload)


# ---------------------------------------------------------------------------
# 组织变更（总册 9.8 / 39.2）—— 写操作
# ---------------------------------------------------------------------------


def organization_changes(request):
    """POST /api/hr/v1/structure/organization-changes —— 创建组织变更 case。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not has_hr02_permission(request.user, "hr.structure.organization.change.submit"):
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

    from hr_structure.services.organization_change import (
        Hr02ServiceError,
        OrganizationChangeService,
    )

    try:
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
            request, scope.tenant_id, timezone.localdate(),
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
    if not has_hr02_permission(request.user, "hr.structure.position.manage"):
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
            count=body.get("count", 1),
            fte=body.get("fte", "1.00"),
            idempotency_key=idempotency_key,
        )
    except PositionServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)
    except (TypeError, ValueError):
        return _error(request, "HR02_INVALID_REQUEST", "count/fte 参数无效", status=400)
    except IntegrityError:
        # 并发同 key 幂等重试撞唯一约束（复审 P1：TOCTOU）→ 重查并幂等返回
        from hr_structure.models import HrPositionReservation

        existing = HrPositionReservation.objects.filter(
            tenant_id=scope.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            r = existing
        else:
            return _error(request, "HR02_POSITION_NOT_AVAILABLE", "预占创建冲突，请重试", status=409)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
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
    if not has_hr02_permission(request.user, "hr.structure.position.manage"):
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
            request, scope.tenant_id, timezone.localdate(),
            reservation={"id": r.id, "reservationNo": r.reservation_no, "status": r.status},
        ),
    )


@require_GET
def position_reservations_list(request):
    if not has_hr02_permission(request.user, "hr.structure.position.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位预占查看权限", status=403)
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
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), items=items))


@require_GET
def position_availability(request):
    if not has_hr02_permission(request.user, "hr.structure.position.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位查看权限", status=403)
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


# ---------------------------------------------------------------------------
# 党政组织与业务关系（总册 10 节）—— HR02-02
# ---------------------------------------------------------------------------


def org_relations(request):
    """GET/POST /api/hr/v1/structure/org-relations —— 查询或创建关系。"""
    import json

    if request.method == "GET":
        return org_relations_list(request)
    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 GET/POST", status=405)
    if not has_hr02_permission(request.user, "hr.structure.org_relation.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无关系管理权限", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        from datetime import date as _date

        validity_from = _date.fromisoformat(body.get("validityFrom", ""))
    except ValueError:
        return _error(request, "HR02_INVALID_REQUEST", "无效生效日期", status=400)

    try:
        from hr_structure.services.relation import RelationService, RelationServiceError

        svc = RelationService(scope, actor=str(getattr(request.user, "id", "")))
        rel = svc.create_relation(
            source_org_id=body.get("sourceOrgId"),
            target_org_id=body.get("targetOrgId"),
            relation_type=body.get("relationType"),
            validity_from=validity_from,
            validity_to=(
                _date.fromisoformat(body["validityTo"]) if body.get("validityTo") else None
            ),
        )
    except RelationServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)
    except KeyError:
        return _error(request, "HR02_INVALID_REQUEST", "缺少必需字段", status=400)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
            relation={"id": rel.id, "sourceOrgId": rel.source_org_id_id, "targetOrgId": rel.target_org_id_id, "type": rel.relation_type},
        ),
        status=201,
    )


def org_relation_close(request, relation_id):
    """POST /api/hr/v1/structure/org-relations/{id}/close"""
    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not has_hr02_permission(request.user, "hr.structure.org_relation.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无关系管理权限", status=403)

    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        from hr_structure.services.relation import RelationService, RelationServiceError

        rel = RelationService(scope).close(relation_id)
    except RelationServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)

    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), relation={"id": rel.id, "status": rel.status}))


@require_GET
def org_relations_list(request):
    """GET /api/hr/v1/structure/org-relations —— 关系列表/冲突检测。"""
    if not has_hr02_permission(request.user, "hr.structure.org_relation.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无关系查看权限", status=403)
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrOrganizationRelation

    qs = HrOrganizationRelation.objects.filter(
        tenant_id=scope.tenant_id, status="ACTIVE"
    ).select_related("source_org_id", "target_org_id")
    if request.GET.get("sourceOrgId"):
        qs = qs.filter(source_org_id_id=request.GET["sourceOrgId"])
    items = [
        {
            "id": r.id,
            "sourceOrgId": r.source_org_id_id,
            "sourceOrgCode": r.source_org_id.stable_code,
            "targetOrgId": r.target_org_id_id,
            "targetOrgCode": r.target_org_id.stable_code,
            "relationType": r.relation_type,
            "validityFrom": r.validity_from.isoformat(),
            "validityTo": r.validity_to.isoformat() if r.validity_to else None,
        }
        for r in qs.order_by("-id")[:200]
    ]
    # 冲突检测
    from hr_structure.services.relation import RelationService

    conflicts = RelationService(scope).detect_conflicts()
    return _json(
        request,
        _root(request, scope.tenant_id, timezone.localdate(), items=items, conflicts=conflicts),
    )


# ---------------------------------------------------------------------------
# 编制方案（总册 11 节）—— HR02-03
# ---------------------------------------------------------------------------


def staffing_plans(request):
    """POST /api/hr/v1/structure/staffing-plans —— 创建方案。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not has_hr02_permission(request.user, "hr.structure.staffing_plan.create"):
        return _error(request, "HR02_SCOPE_DENIED", "无创建编制方案权限", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        from datetime import date as _date

        validity_from = _date.fromisoformat(body.get("validityFrom", ""))
        plan_year = int(body.get("planYear", validity_from.year))
    except ValueError:
        return _error(request, "HR02_INVALID_REQUEST", "无效日期/年份", status=400)

    try:
        from hr_structure.services.staffing_plan import StaffingPlanService

        svc = StaffingPlanService(scope, actor=str(getattr(request.user, "id", "")))
        plan = svc.create_plan(
            code=body.get("code", ""),
            name=body.get("name", ""),
            plan_year=plan_year,
            validity_from=validity_from,
            basis_document_no=body.get("basisDocumentNo", ""),
        )
    except (ValueError, IntegrityError) as exc:
        return _error(request, "HR02_INVALID_REQUEST", str(exc), status=422)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
            plan={"id": plan.id, "code": plan.code, "status": plan.status},
        ),
        status=201,
    )


def staffing_plan_action(request, plan_id, action):
    """POST /api/hr/v1/structure/staffing-plans/{id}/validate|submit|approve"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)

    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrStaffingPlan

    plan = HrStaffingPlan.objects.filter(tenant_id=scope.tenant_id, id=plan_id).first()
    if plan is None:
        return _error(request, "HR02_ORG_NOT_FOUND", "方案不存在", status=404)

    try:
        from hr_structure.services.staffing_plan import StaffingPlanService

        svc = StaffingPlanService(scope, actor=str(getattr(request.user, "id", "")))
        if action == "validate":
            result = svc.preflight(plan)
            issues = [{"level": i.level, "code": i.code, "message": i.message} for i in result.issues]
            return _json(request, _root(request, scope.tenant_id, timezone.localdate(), issues=issues, hasBlocker=result.has_blocker))
        if action == "submit":
            if not has_hr02_permission(request.user, "hr.structure.staffing_plan.submit"):
                return _error(request, "HR02_SCOPE_DENIED", "无提交权限", status=403)
            locked_plan = svc.submit(plan)
            return _json(
                request,
                _root(
                    request, scope.tenant_id, timezone.localdate(),
                    plan={"id": locked_plan.id, "status": locked_plan.status, "versionNo": locked_plan.version_no},
                ),
            )
        if action == "approve":
            if not has_hr02_permission(request.user, "hr.structure.staffing_plan.approve"):
                return _error(request, "HR02_SCOPE_DENIED", "无批准权限", status=403)
            plan = svc.approve(plan)
            return _json(request, _root(request, scope.tenant_id, timezone.localdate(), plan={"id": plan.id, "status": plan.status}))
        if action == "activate":
            if not has_hr02_permission(request.user, "hr.structure.staffing_plan.activate"):
                return _error(request, "HR02_SCOPE_DENIED", "无生效方案权限", status=403)
            plan = svc.activate(plan)
            return _json(
                request,
                _root(
                    request,
                    scope.tenant_id,
                    timezone.localdate(),
                    plan={
                        "id": plan.id,
                        "status": plan.status,
                        "versionNo": plan.version_no,
                    },
                ),
            )
        return _error(request, "HR02_INVALID_REQUEST", "未知动作", status=400)
    except ValueError as exc:
        return _error(request, "HR02_INVALID_REQUEST", str(exc), status=422)


def staffing_plan_lines(request, plan_id):
    """GET/POST 编制方案人员、岗位与领导职数明细。"""
    import json

    if request.method not in {"GET", "POST"}:
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 GET/POST", status=405)
    permission = (
        "hr.structure.staffing_plan.view"
        if request.method == "GET"
        else "hr.structure.staffing_plan.edit"
    )
    if not has_hr02_permission(request.user, permission):
        return _error(request, "HR02_SCOPE_DENIED", "无编制方案明细权限", status=403)
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrStaffingPlan

    plan = HrStaffingPlan.objects.filter(
        tenant_id=scope.tenant_id, id=plan_id
    ).first()
    if plan is None:
        return _error(request, "HR02_ORG_NOT_FOUND", "编制方案不存在", status=404)

    if request.method == "POST":
        try:
            body = json.loads(request.body or "{}")
            line_type = body.get("lineType")
            from hr_structure.services.staffing_plan import StaffingPlanService

            service = StaffingPlanService(
                scope, actor=str(getattr(request.user, "id", ""))
            )
            common = {
                "plan_id": plan.id,
                "organization_id": body.get("organizationId"),
            }
            if line_type == "HEADCOUNT":
                line = service.add_headcount_line(
                    **common,
                    staffing_basis=body.get("staffingBasis"),
                    worker_category=body.get("workerCategory", ""),
                    authorized_headcount=body.get("authorizedHeadcount"),
                    reserve_headcount=body.get("reserveHeadcount", 0),
                    control_mode=body.get("controlMode", "HARD"),
                    notes=body.get("notes", ""),
                )
            elif line_type == "POSITION":
                line = service.add_position_line(
                    **common,
                    post_category=body.get("postCategory"),
                    post_grade=body.get("postGrade", ""),
                    post_catalog_id=body.get("postCatalogId"),
                    authorized_positions=body.get("authorizedPositions"),
                    authorized_fte=body.get("authorizedFte"),
                    control_mode=body.get("controlMode", "HARD"),
                )
            elif line_type == "LEADERSHIP":
                line = service.add_leadership_line(
                    **common,
                    leadership_level=body.get("leadershipLevel"),
                    quota_count=body.get("quotaCount"),
                    control_mode=body.get("controlMode", "HARD"),
                )
            else:
                return _error(request, "HR02_INVALID_REQUEST", "明细类型非法", status=400)
        except json.JSONDecodeError:
            return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
        except ValueError as exc:
            return _error(request, "HR02_INVALID_REQUEST", str(exc), status=422)
        return _json(
            request,
            _root(
                request,
                scope.tenant_id,
                timezone.localdate(),
                line={"id": line.id, "lineType": line_type},
            ),
            status=201,
        )

    items = []
    for line in plan.headcount_lines.select_related("organization_id").order_by("id"):
        items.append({
            "id": line.id,
            "lineType": "HEADCOUNT",
            "organizationId": line.organization_id_id,
            "organizationCode": line.organization_id.stable_code,
            "staffingBasis": line.staffing_basis,
            "workerCategory": line.worker_category,
            "authorizedHeadcount": line.authorized_headcount,
            "reserveHeadcount": line.reserve_headcount,
            "controlMode": line.control_mode,
        })
    for line in plan.position_lines.select_related("organization_id").order_by("id"):
        items.append({
            "id": line.id,
            "lineType": "POSITION",
            "organizationId": line.organization_id_id,
            "organizationCode": line.organization_id.stable_code,
            "postCategory": line.post_category,
            "postGrade": line.post_grade,
            "authorizedPositions": line.authorized_positions,
            "authorizedFte": str(line.authorized_fte),
            "controlMode": line.control_mode,
        })
    for line in plan.leadership_lines.select_related("organization_id").order_by("id"):
        items.append({
            "id": line.id,
            "lineType": "LEADERSHIP",
            "organizationId": line.organization_id_id,
            "organizationCode": line.organization_id.stable_code,
            "leadershipLevel": line.leadership_level,
            "quotaCount": line.quota_count,
            "controlMode": line.control_mode,
        })
    return _json(
        request,
        _root(
            request,
            scope.tenant_id,
            timezone.localdate(),
            plan={"id": plan.id, "code": plan.code, "status": plan.status},
            items=items,
        ),
    )


@require_GET
def staffing_plans_list(request):
    if not has_hr02_permission(request.user, "hr.structure.staffing_plan.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无编制方案查看权限", status=403)
    """GET /api/hr/v1/structure/staffing-plans —— 方案列表。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrStaffingPlan

    items = [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "planYear": p.plan_year,
            "status": p.status,
            "validityFrom": p.validity_from.isoformat(),
        }
        for p in HrStaffingPlan.objects.filter(tenant_id=scope.tenant_id).order_by("-plan_year")
    ]
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), items=items))


# ---------------------------------------------------------------------------
# 岗位目录（总册 12 节）—— HR02-04
# ---------------------------------------------------------------------------


def post_catalogs(request):
    """POST /api/hr/v1/structure/post-catalogs —— 创建岗位标准。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not has_hr02_permission(request.user, "hr.structure.post_catalog.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位目录管理权限", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        from hr_structure.services.post_catalog import PostCatalogService

        svc = PostCatalogService(scope, actor=str(getattr(request.user, "id", "")))
        catalog = svc.create_catalog(
            stable_code=body.get("stableCode", ""),
            name=body.get("name", ""),
            category=body.get("category", "PROFESSIONAL_TECHNICAL"),
            subcategory=body.get("subcategory", ""),
        )
    except (ValueError, IntegrityError) as exc:
        return _error(request, "HR02_INVALID_REQUEST", str(exc), status=422)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
            catalog={"id": catalog.id, "stableCode": catalog.stable_code},
        ),
        status=201,
    )


@require_GET
def post_catalogs_list(request):
    if not has_hr02_permission(request.user, "hr.structure.post_catalog.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位目录查看权限", status=403)
    """GET /api/hr/v1/structure/post-catalogs —— 岗位目录列表。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrPostCatalog, HrPostCatalogVersion

    items = []
    for catalog in HrPostCatalog.objects.filter(tenant_id=scope.tenant_id).order_by("stable_code"):
        version = (
            HrPostCatalogVersion.objects.filter(catalog_id=catalog, status="ACTIVE")
            .order_by("-version_no")
            .first()
        )
        items.append(
            {
                "id": catalog.id,
                "activeVersionId": version.id if version else None,
                "stableCode": catalog.stable_code,
                "name": version.name if version else "",
                "category": version.category if version else "",
                "subcategory": version.subcategory if version else "",
                "controlMode": version.control_mode if version else "",
                "versionNo": version.version_no if version else 0,
            }
        )
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), items=items))


@require_GET
def post_grade_schemes(request):
    if not has_hr02_permission(request.user, "hr.structure.post_catalog.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位目录查看权限", status=403)
    """GET /api/hr/v1/structure/post-grade-schemes —— 岗位等级方案。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrPostGradeScheme

    items = [
        {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "category": s.category,
            "grades": [
                {"id": g.id, "code": g.code, "name": g.name, "rankOrder": g.rank_order, "levelNumber": g.level_number}
                for g in s.grades.order_by("rank_order")
            ],
        }
        for s in HrPostGradeScheme.objects.filter(tenant_id=scope.tenant_id).order_by("code")
    ]
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), items=items))


# ---------------------------------------------------------------------------
# 组织岗位历史与重组（总册 14 节）—— HR02-06
# ---------------------------------------------------------------------------


@require_GET
def change_cases_list(request):
    if not has_hr02_permission(request.user, "hr.structure.organization.history.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织岗位历史查看权限", status=403)
    """GET /api/hr/v1/structure/change-cases —— 变更 case 列表。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrStructureChangeCase

    items = [
        {
            "id": c.id,
            "caseNo": c.case_no,
            "changeType": c.change_type,
            "title": c.title,
            "status": c.status,
            "requestedEffectiveDate": c.requested_effective_date.isoformat(),
        }
        for c in HrStructureChangeCase.objects.filter(tenant_id=scope.tenant_id).order_by("-id")
    ]
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), items=items))


def change_case_action(request, case_id, action):
    """POST /api/hr/v1/structure/change-cases/{id}/{action}
    action: preview|submit|approve|schedule|execute
    """
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)

    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrStructureChangeCase

    case = HrStructureChangeCase.objects.filter(tenant_id=scope.tenant_id, id=case_id).first()
    if case is None:
        return _error(request, "HR02_ORG_NOT_FOUND", "变更 case 不存在", status=404)

    try:
        from hr_structure.services.reorganization import (
            ReorganizationService,
            ReorgServiceError,
        )

        svc = ReorganizationService(scope, actor=str(getattr(request.user, "id", "")))
        if action == "preview":
            if not has_hr02_permission(request.user, "hr.structure.reorg.preview"):
                return _error(request, "HR02_SCOPE_DENIED", "无影响分析权限", status=403)
            impact = svc.impact_analysis(case)
            return _json(request, _root(request, scope.tenant_id, timezone.localdate(), **impact))
        if action == "submit":
            if not has_hr02_permission(request.user, "hr.structure.reorg.submit"):
                return _error(request, "HR02_SCOPE_DENIED", "无提交权限", status=403)
            case = svc.submit(case)
        elif action == "approve":
            if not has_hr02_permission(request.user, "hr.structure.reorg.approve"):
                return _error(request, "HR02_SCOPE_DENIED", "无批准权限", status=403)
            case = svc.approve(case)
        elif action == "schedule":
            if not has_hr02_permission(request.user, "hr.structure.reorg.execute"):
                return _error(request, "HR02_SCOPE_DENIED", "无调度权限", status=403)
            case = svc.schedule(case)
        elif action == "execute":
            if not has_hr02_permission(request.user, "hr.structure.reorg.execute"):
                return _error(request, "HR02_SCOPE_DENIED", "无执行权限", status=403)
            body = json.loads(request.body or "{}") if request.body else {}
            case = svc.execute_effective(case, execution_key=body.get("executionKey", f"manual-{case.case_no}"))
            if case.status == "FAILED_EFFECT":
                return _error(
                    request, "HR02_REORG_HAS_BLOCKERS",
                    "生效执行失败: " + ((case.execution_result_json or {}).get("error") or "未知错误"),
                    status=409,
                )
        else:
            return _error(request, "HR02_INVALID_REQUEST", "未知动作", status=400)
    except ReorgServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
            case={"id": case.id, "caseNo": case.case_no, "status": case.status},
        ),
    )


@require_POST
def effective_runner_trigger(request):
    """POST /api/hr/v1/structure/effective-runner/run —— 触发到期 case 生效（运维）。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    if not has_hr02_permission(request.user, "hr.structure.reorg.execute"):
        return _error(request, "HR02_SCOPE_DENIED", "无执行权限", status=403)

    from hr_structure.services.effective_runner import run_effective_runner

    result = run_effective_runner(tenant_id=scope.tenant_id)
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), **result))


# ---------------------------------------------------------------------------
# Legacy 迁移 + Projection + Authority Cutover（总册 29/30 节）—— S9/S10
# ---------------------------------------------------------------------------


@require_POST
def projection_run(request):
    """POST /api/hr/v1/structure/projection/run —— 把权威组织投影到 Horilla Department（单向）。

    仅 HR02_AUTHORITY/DUAL_READ_COMPARE 模式允许投影写 Horilla Department
    （总册 30.1：LEGACY_STRUCTURE_ONLY 不得强切/覆盖 legacy）。
    """
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    if not has_hr02_permission(request.user, "hr.structure.organization.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织管理权限", status=403)

    from hr_structure.services.cutover import Hr02CutoverService

    mode = Hr02CutoverService().get_mode(scope.tenant_id)
    if mode not in ("HR02_AUTHORITY", "DUAL_READ_COMPARE"):
        return _error(
            request, "HR02_LEGACY_WRITE_DISABLED",
            "当前 HR02 未进入权威/对账模式，禁止投影写 Horilla Department", status=409,
        )

    from hr_structure.models import HrOrganizationVersion
    from hr_structure.projections.horilla import HorillaStructureProjectionService

    svc = HorillaStructureProjectionService(scope.tenant_id)
    versions = HrOrganizationVersion.objects.filter(
        tenant_id=scope.tenant_id, status="EFFECTIVE", validity_to__isnull=True
    ).select_related("organization_id")
    projected = 0
    for v in versions:
        svc.project_organization(v)
        projected += 1
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), projected=projected, mode=mode))


@require_GET
def projection_reconcile(request):
    if not has_hr02_permission(request.user, "hr.structure.organization.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织管理权限", status=403)
    """GET /api/hr/v1/structure/projection/reconcile —— 对账报告。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.projections.horilla import HorillaStructureProjectionService

    report = HorillaStructureProjectionService(scope.tenant_id).reconcile_report()
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), report=report))


def cutover(request):
    """POST /api/hr/v1/structure/cutover —— 切换 authority mode（tenant 级）。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not request.user.is_superuser:
        return _error(request, "HR02_SCOPE_DENIED", "仅超级管理员可切换", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        from hr_structure.services.cutover import Hr02CutoverService

        svc = Hr02CutoverService(operator=str(getattr(request.user, "username", "")))
        record = svc.set_mode(
            scope.tenant_id,
            body.get("mode", ""),
            reason=body.get("reason", ""),
            reconcile_report_id=body.get("reconcileReportId", ""),
        )
    except ValueError as exc:
        return _error(request, "HR02_INVALID_REQUEST", str(exc), status=422)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
            cutover={"tenantId": record.tenant_id, "mode": record.mode, "oldMode": record.old_mode},
        ),
    )


@require_GET
def cutover_status(request):
    """GET /api/hr/v1/structure/cutover/status —— 当前 tenant 的 authority mode。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.services.cutover import Hr02CutoverService

    mode = Hr02CutoverService().get_mode(scope.tenant_id)
    return _json(request, _root(request, scope.tenant_id, timezone.localdate(), mode=mode))


# ---------------------------------------------------------------------------
# 岗位台账列表/概览（HR02-05）
# ---------------------------------------------------------------------------


def positions_list(request):
    """GET/POST /api/hr/v1/structure/positions —— 查询或创建岗位。"""
    import json

    if request.method not in {"GET", "POST"}:
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 GET/POST", status=405)
    permission = (
        "hr.structure.position.view"
        if request.method == "GET"
        else "hr.structure.position.manage"
    )
    if not has_hr02_permission(request.user, permission):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位台账权限", status=403)
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if request.method == "POST":
        try:
            body = json.loads(request.body or "{}")
            from datetime import date as _date

            from hr_structure.services.position import (
                PositionService,
                PositionServiceError,
            )

            validity_from = (
                _date.fromisoformat(body["validityFrom"])
                if body.get("validityFrom")
                else timezone.localdate()
            )
            kwargs = {
                "max_incumbents": body.get("maxIncumbents", 1),
                "position_type": body.get("positionType", "REGULAR"),
                "allow_multiple_incumbents": PositionService._bool_value(
                    body.get("allowMultipleIncumbents", False)
                ),
            }
            if body.get("postGradeId") not in (None, ""):
                kwargs["post_grade_id_id"] = int(body["postGradeId"])
            position = PositionService(
                scope, actor=str(getattr(request.user, "id", ""))
            ).create_position(
                position_code=body.get("positionCode"),
                organization_id=body.get("organizationId"),
                post_catalog_version_id=body.get("postCatalogVersionId"),
                planned_fte=body.get("plannedFte", "1.00"),
                validity_from=validity_from,
                **kwargs,
            )
        except json.JSONDecodeError:
            return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
        except (TypeError, ValueError) as exc:
            return _error(request, "HR02_INVALID_REQUEST", str(exc), status=400)
        except PositionServiceError as exc:
            return _error(request, exc.code, exc.message, status=exc.http_status)
        return _json(
            request,
            _root(
                request,
                scope.tenant_id,
                as_of,
                position={
                    "id": position.id,
                    "positionCode": position.position_code,
                    "lifecycleStatus": position.lifecycle_status,
                    "version": position.version,
                },
            ),
            status=201,
        )

    from hr_structure.selectors.position import PositionSelector

    try:
        page = int(request.GET.get("page", 1) or 1)
        page_size = int(request.GET.get("page_size", 20) or 20)
    except (TypeError, ValueError):
        return _error(request, "HR02_INVALID_REQUEST", "分页参数必须是整数", status=400)
    if page < 1:
        return _error(request, "HR02_INVALID_REQUEST", "页码必须从 1 开始", status=400)
    page_size = min(max(page_size, 1), 100)
    selector = PositionSelector(scope, as_of=as_of)
    result = selector.list_positions(
        organization_id=request.GET.get("organizationId"),
        lifecycle_status=request.GET.get("lifecycleStatus"),
        page=page,
        page_size=page_size,
    )
    return _json(request, _root(request, scope.tenant_id, as_of, **result))


def position_detail(request, position_id):
    """GET/PATCH 岗位详情与非结构性属性变更。"""
    import json

    if request.method not in {"GET", "PATCH"}:
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 GET/PATCH", status=405)
    permission = (
        "hr.structure.position.view"
        if request.method == "GET"
        else "hr.structure.position.manage"
    )
    if not has_hr02_permission(request.user, permission):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位台账权限", status=403)
    try:
        scope = _make_scope(request)
        as_of = _parse_as_of(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    if request.method == "GET":
        from hr_structure.selectors.position import PositionSelector

        item = PositionSelector(scope, as_of=as_of).get_position(position_id)
        if item is None:
            return _error(request, "HR02_POSITION_NOT_FOUND", "岗位不存在", status=404)
        return _json(request, _root(request, scope.tenant_id, as_of, position=item))
    try:
        body = json.loads(request.body or "{}")
        mapping = {
            "postCatalogVersionId": "post_catalog_version_id",
            "postGradeId": "post_grade_id",
            "positionType": "position_type",
            "plannedFte": "planned_fte",
            "maxIncumbents": "max_incumbents",
            "allowMultipleIncumbents": "allow_multiple_incumbents",
        }
        changes = {
            target: body[source]
            for source, target in mapping.items()
            if source in body
        }
        from hr_structure.services.position import PositionService, PositionServiceError

        position = PositionService(
            scope, actor=str(getattr(request.user, "id", ""))
        ).update_position(
            position_id,
            expected_version=body.get("version"),
            **changes,
        )
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except (TypeError, ValueError):
        return _error(request, "HR02_INVALID_REQUEST", "岗位参数格式非法", status=400)
    except PositionServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)
    return _json(
        request,
        _root(
            request,
            scope.tenant_id,
            as_of,
            position={
                "id": position.id,
                "positionCode": position.position_code,
                "lifecycleStatus": position.lifecycle_status,
                "version": position.version,
            },
        ),
    )


def position_action(request, position_id, action):
    """POST 岗位冻结、解冻或关闭。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if action == "validate" and not has_hr02_permission(
        request.user, "hr.structure.staffing_plan.view"
    ):
        return _error(request, "HR02_SCOPE_DENIED", "无编制方案查看权限", status=403)
    permission = (
        "hr.structure.position.close"
        if action == "close"
        else "hr.structure.position.freeze"
    )
    if not has_hr02_permission(request.user, permission):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位状态变更权限", status=403)
    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}") if request.body else {}
        from hr_structure.services.position import PositionService, PositionServiceError

        service = PositionService(scope, actor=str(getattr(request.user, "id", "")))
        reason = str(body.get("reason", "")).strip()
        if action == "freeze":
            position = service.freeze(position_id, reason)
        elif action == "unfreeze":
            position = service.unfreeze(position_id, reason)
        elif action == "close":
            position = service.close(position_id, reason)
        else:
            return _error(request, "HR02_INVALID_REQUEST", "未知岗位动作", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except PositionServiceError as exc:
        return _error(request, exc.code, exc.message, status=exc.http_status)
    return _json(
        request,
        _root(
            request,
            scope.tenant_id,
            timezone.localdate(),
            position={
                "id": position.id,
                "lifecycleStatus": position.lifecycle_status,
                "version": position.version,
            },
        ),
    )


@require_GET
def position_control_summary(request):
    if not has_hr02_permission(request.user, "hr.structure.position.view"):
        return _error(request, "HR02_SCOPE_DENIED", "无岗位查看权限", status=403)
    """GET /api/hr/v1/structure/position-control/summary —— 台账概览。"""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.selectors.position import PositionSelector

    summary = PositionSelector(scope, as_of=as_of).control_summary()
    return _json(
        request,
        _root(request, scope.tenant_id, as_of, **summary),
    )


# ---------------------------------------------------------------------------
# 组织 Excel 导入（总册 23 节）—— 预检 / 确认落库
# ---------------------------------------------------------------------------


def organization_import(request):
    """POST /api/hr/v1/structure/organization-import
    body: {"rows": [{组织代码,组织名称,组织类型,组织维度,上级组织代码,排序}], "dryRun": bool}
    """
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not has_hr02_permission(request.user, "hr.structure.organization.manage"):
        return _error(request, "HR02_SCOPE_DENIED", "无组织管理权限", status=403)

    try:
        scope = _make_scope(request)
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error(request, "HR02_INVALID_REQUEST", "请求体不是合法 JSON", status=400)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    rows = body.get("rows", [])
    dry_run = body.get("dryRun", True)

    try:
        from hr_structure.imports.organization_import import OrganizationImportService

        svc = OrganizationImportService(scope, actor=str(getattr(request.user, "id", "")))
        result = svc.import_rows(rows, dry_run=dry_run)
    except Exception:
        return _error(request, "HR02_INVALID_REQUEST", "导入失败", status=422)

    return _json(
        request,
        _root(
            request, scope.tenant_id, timezone.localdate(),
            created=result.created,
            errors=[{"row": e.row, "code": e.code, "message": e.message, "field": e.field} for e in result.errors],
            hasErrors=result.has_errors,
            dryRun=dry_run,
        ),
    )
