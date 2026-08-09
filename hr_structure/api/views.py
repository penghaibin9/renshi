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
    """服务端解析 scope：认证 + tenant + 用户授权范围（总册 35.1，不信前端任意值）。"""
    if not getattr(request.user, "is_authenticated", False):
        raise HrContextError("HR02_SCOPE_DENIED", "请先登录")
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrContextError("HR02_TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    # scope_type 白名单由 resolve_scope 校验；scope_id 仅当用户是 superuser 或拥有组织权限时接受
    scope_type = request.GET.get("scope_type", "SCHOOL")
    if scope_type != "SCHOOL" and not (request.user.is_superuser or request.user.has_perm("hr.organization.view")):
        raise HrContextError("HR02_SCOPE_DENIED", "无该数据范围权限")
    return resolve_scope(
        tenant_id,
        scope_type=scope_type,
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


# ---------------------------------------------------------------------------
# 党政组织与业务关系（总册 10 节）—— HR02-02
# ---------------------------------------------------------------------------


def org_relations(request):
    """POST /api/hr/v1/structure/org-relations —— 创建关系。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.org_relation.manage")):
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
            request, scope.tenant_id, date.today(),
            relation={"id": rel.id, "sourceOrgId": rel.source_org_id_id, "targetOrgId": rel.target_org_id_id, "type": rel.relation_type},
        ),
        status=201,
    )


def org_relation_close(request, relation_id):
    """POST /api/hr/v1/structure/org-relations/{id}/close"""
    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.org_relation.manage")):
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

    return _json(request, _root(request, scope.tenant_id, date.today(), relation={"id": rel.id, "status": rel.status}))


@require_GET
def org_relations_list(request):
    """GET /api/hr/v1/structure/org-relations —— 关系列表/冲突检测。"""
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
        _root(request, scope.tenant_id, date.today(), items=items, conflicts=conflicts),
    )


# ---------------------------------------------------------------------------
# 编制方案（总册 11 节）—— HR02-03
# ---------------------------------------------------------------------------


def staffing_plans(request):
    """POST /api/hr/v1/structure/staffing-plans —— 创建方案。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.staffing_plan.create")):
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
    except Exception:
        return _error(request, "HR02_INVALID_REQUEST", "创建方案失败", status=422)

    return _json(
        request,
        _root(
            request, scope.tenant_id, date.today(),
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
            return _json(request, _root(request, scope.tenant_id, date.today(), issues=issues, hasBlocker=result.has_blocker))
        if action == "submit":
            if not (request.user.is_superuser or request.user.has_perm("hr.staffing_plan.submit")):
                return _error(request, "HR02_SCOPE_DENIED", "无提交权限", status=403)
            locked_plan = svc.submit(plan)
            return _json(
                request,
                _root(
                    request, scope.tenant_id, date.today(),
                    plan={"id": locked_plan.id, "status": locked_plan.status, "versionNo": locked_plan.version_no},
                ),
            )
        if action == "approve":
            if not (request.user.is_superuser or request.user.has_perm("hr.staffing_plan.approve")):
                return _error(request, "HR02_SCOPE_DENIED", "无批准权限", status=403)
            plan = svc.approve(plan)
            return _json(request, _root(request, scope.tenant_id, date.today(), plan={"id": plan.id, "status": plan.status}))
        return _error(request, "HR02_INVALID_REQUEST", "未知动作", status=400)
    except ValueError as exc:
        return _error(request, "HR02_INVALID_REQUEST", str(exc), status=422)


@require_GET
def staffing_plans_list(request):
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
    return _json(request, _root(request, scope.tenant_id, date.today(), items=items))


# ---------------------------------------------------------------------------
# 岗位目录（总册 12 节）—— HR02-04
# ---------------------------------------------------------------------------


def post_catalogs(request):
    """POST /api/hr/v1/structure/post-catalogs —— 创建岗位标准。"""
    import json

    if request.method != "POST":
        return _error(request, "HR02_METHOD_NOT_ALLOWED", "仅支持 POST", status=405)
    if not (request.user.is_superuser or request.user.has_perm("hr.post_catalog.manage")):
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
    except Exception:
        return _error(request, "HR02_INVALID_REQUEST", "创建岗位目录失败", status=422)

    return _json(
        request,
        _root(
            request, scope.tenant_id, date.today(),
            catalog={"id": catalog.id, "stableCode": catalog.stable_code},
        ),
        status=201,
    )


@require_GET
def post_catalogs_list(request):
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
                "stableCode": catalog.stable_code,
                "name": version.name if version else "",
                "category": version.category if version else "",
                "subcategory": version.subcategory if version else "",
                "controlMode": version.control_mode if version else "",
                "versionNo": version.version_no if version else 0,
            }
        )
    return _json(request, _root(request, scope.tenant_id, date.today(), items=items))


@require_GET
def post_grade_schemes(request):
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
    return _json(request, _root(request, scope.tenant_id, date.today(), items=items))


# ---------------------------------------------------------------------------
# 组织岗位历史与重组（总册 14 节）—— HR02-06
# ---------------------------------------------------------------------------


@require_GET
def change_cases_list(request):
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
    return _json(request, _root(request, scope.tenant_id, date.today(), items=items))


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
        from hr_structure.services.reorganization import ReorganizationService, ReorgServiceError

        svc = ReorganizationService(scope, actor=str(getattr(request.user, "id", "")))
        if action == "preview":
            impact = svc.impact_analysis(case)
            return _json(request, _root(request, scope.tenant_id, date.today(), **impact))
        if action == "submit":
            if not (request.user.is_superuser or request.user.has_perm("hr.reorg.submit")):
                return _error(request, "HR02_SCOPE_DENIED", "无提交权限", status=403)
            case = svc.submit(case)
        elif action == "approve":
            if not (request.user.is_superuser or request.user.has_perm("hr.reorg.approve")):
                return _error(request, "HR02_SCOPE_DENIED", "无批准权限", status=403)
            case = svc.approve(case)
        elif action == "schedule":
            if not (request.user.is_superuser or request.user.has_perm("hr.reorg.execute")):
                return _error(request, "HR02_SCOPE_DENIED", "无调度权限", status=403)
            case = svc.schedule(case)
        elif action == "execute":
            if not (request.user.is_superuser or request.user.has_perm("hr.reorg.execute")):
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
            request, scope.tenant_id, date.today(),
            case={"id": case.id, "caseNo": case.case_no, "status": case.status},
        ),
    )


@require_GET
def effective_runner_trigger(request):
    """GET /api/hr/v1/structure/effective-runner/run —— 触发到期 case 生效（运维）。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    if not (request.user.is_superuser or request.user.has_perm("hr.reorg.execute")):
        return _error(request, "HR02_SCOPE_DENIED", "无执行权限", status=403)

    from hr_structure.services.effective_runner import run_effective_runner

    result = run_effective_runner(tenant_id=scope.tenant_id)
    return _json(request, _root(request, scope.tenant_id, date.today(), **result))


# ---------------------------------------------------------------------------
# Legacy 迁移 + Projection + Authority Cutover（总册 29/30 节）—— S9/S10
# ---------------------------------------------------------------------------


@require_GET
def projection_run(request):
    """GET /api/hr/v1/structure/projection/run —— 把权威组织投影到 Horilla Department（单向）。

    仅 HR02_AUTHORITY/DUAL_READ_COMPARE 模式允许投影写 Horilla Department
    （总册 30.1：LEGACY_STRUCTURE_ONLY 不得强切/覆盖 legacy）。
    """
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    if not (request.user.is_superuser or request.user.has_perm("hr.organization.manage")):
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
    return _json(request, _root(request, scope.tenant_id, date.today(), projected=projected, mode=mode))


@require_GET
def projection_reconcile(request):
    """GET /api/hr/v1/structure/projection/reconcile —— 对账报告。"""
    try:
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.projections.horilla import HorillaStructureProjectionService

    report = HorillaStructureProjectionService(scope.tenant_id).reconcile_report()
    return _json(request, _root(request, scope.tenant_id, date.today(), report=report))


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
            request, scope.tenant_id, date.today(),
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
    return _json(request, _root(request, scope.tenant_id, date.today(), mode=mode))


# ---------------------------------------------------------------------------
# 岗位台账列表/概览（HR02-05）
# ---------------------------------------------------------------------------


@require_GET
def positions_list(request):
    """GET /api/hr/v1/structure/positions —— 岗位列表（DB 分页）。"""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.selectors.position import PositionSelector

    page = int(request.GET.get("page", 1) or 1)
    page_size = int(request.GET.get("page_size", 20) or 20)
    page_size = min(max(page_size, 1), 100)
    selector = PositionSelector(scope, as_of=as_of)
    result = selector.list_positions(
        organization_id=request.GET.get("organizationId"),
        lifecycle_status=request.GET.get("lifecycleStatus"),
        page=page,
        page_size=page_size,
    )
    return _json(request, _root(request, scope.tenant_id, as_of, **result))


@require_GET
def position_control_summary(request):
    """GET /api/hr/v1/structure/position-control/summary —— 台账概览。"""
    try:
        as_of = _parse_as_of(request)
        scope = _make_scope(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    from hr_structure.models import HrPosition, HrPositionReservation
    from django.db.models import Sum
    from django.utils import timezone as _tz

    qs = HrPosition.objects.filter(
        tenant_id=scope.tenant_id,
        validity_from__lte=as_of,
        lifecycle_status__in=("ACTIVE", "FROZEN"),
    )
    authorized = qs.count()
    frozen = qs.filter(lifecycle_status="FROZEN").count()
    active = authorized - frozen
    held = (
        HrPositionReservation.objects.filter(
            tenant_id=scope.tenant_id, status="HELD", expires_at__gt=_tz.now()
        ).aggregate(t=Sum("reserved_count"))["t"]
        or 0
    )
    # occupied: HR03 正式 assignment（占位，当前用 reservation）
    occupied = held
    vacant = max(0, active - occupied)
    over = max(0, occupied - active)
    return _json(
        request,
        _root(
            request, scope.tenant_id, as_of,
            authorized=authorized, occupied=occupied, vacant=vacant,
            frozen=frozen, over=over,
        ),
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
    if not (request.user.is_superuser or request.user.has_perm("hr.organization.manage")):
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
            request, scope.tenant_id, date.today(),
            created=result.created,
            errors=[{"row": e.row, "code": e.code, "message": e.message, "field": e.field} for e in result.errors],
            hasErrors=result.has_errors,
            dryRun=dry_run,
        ),
    )
