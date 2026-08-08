"""
hr_control_center/api/views.py

HR01 API views —— 统一 version envelope + 错误处理。

硬合同（总册 31 节）：
- 所有 bootstrap/list response root 必须包含 apiVersion/schemaVersion/requestId/generatedAt。
- error envelope 统一；内部 traceback 不直接返回浏览器。
- 越权不能靠 200 + empty list；fail-closed。
"""

from __future__ import annotations

import logging
import uuid

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from hr_control_center.context import (
    HrContextError,
    build_hr_context,
    resolve_tenant_from_request,
)
from hr_control_center.permissions import require_hr_permission
from hr_control_center.providers.base import HrProviderError
from hr_control_center.services.overview_service import OverviewService

logger = logging.getLogger(__name__)

API_VERSION = "1"
SCHEMA_VERSION = "1.0"


def _request_id(request) -> str:
    rid = getattr(request, "hr_request_id", None)
    if not rid:
        rid = uuid.uuid4().hex
        request.hr_request_id = rid
    return rid


def _api_root(request) -> dict:
    return {
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _request_id(request),
        "generatedAt": None,  # 由 _json 填充
    }


def _json(request, payload: dict, status: int = 200) -> JsonResponse:
    from django.utils import timezone

    payload["generatedAt"] = timezone.now().isoformat()
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _error(request, code: str, message: str, status: int, details=None) -> JsonResponse:
    body = _api_root(request)
    body["error"] = {
        "code": code,
        "message": message,
        "details": details,
    }
    return _json(request, body, status=status)


def _make_context(request):
    """从请求构造 HrRequestContext（服务端重新验证 tenant/scope，不信任前端参数）。"""
    tenant_id = resolve_tenant_from_request(request)
    if tenant_id is None:
        raise HrContextError(
            "TENANT_CONTEXT_REQUIRED", "请选择当前学校（多学校账号需明确学校上下文）"
        )

    scope_type = request.GET.get("scope_type", "SCHOOL")
    scope_org_id = request.GET.get("scope_id")
    if scope_org_id in (None, "", "null"):
        scope_org_id = None
    else:
        try:
            scope_org_id = int(scope_org_id)
        except (TypeError, ValueError):
            raise HrContextError("SCOPE_NOT_ALLOWED", "scope_id 必须是整数")

    return build_hr_context(
        tenant_id=tenant_id,
        school_timezone=request.GET.get("school_timezone") or "Asia/Shanghai",
        user_id=request.user.id,
        as_of=request.GET.get("as_of"),
        period_from=request.GET.get("period_from"),
        period_to=request.GET.get("period_to"),
        scope_type=scope_type,
        scope_org_id=scope_org_id,
        authority_mode=request.GET.get("authority_mode", "LEGACY_ONLY"),
    )


@require_GET
def home_bootstrap(request):
    """GET /api/hr/v1/home/bootstrap —— 首屏聚合。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    # 校验权限：bootstrap 需 hr.dashboard.view（覆盖层）
    try:
        if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.view")):
            return _error(request, "PERMISSION_DENIED", "无查看人事工作台权限", status=403)
        context = _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    try:
        service = OverviewService()
        payload = service.get_bootstrap(context)
    except HrProviderError as exc:
        logger.warning(str(exc))
        return _error(
            request,
            "PROVIDER_UNAVAILABLE",
            "部分指标暂时无法计算",
            status=503,
            details={"provider": exc.provider_key, "metric": exc.metric_key},
        )
    except Exception as exc:  # 兜底：请求级错误必须可见、可追踪，不吞
        logger.exception("bootstrap failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


@require_GET
def home_metrics(request):
    """GET /api/hr/v1/home/overview/metrics —— 6 核心 KPI（bootstrap 已含，独立提供便于刷新）。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.view")):
        return _error(request, "PERMISSION_DENIED", "无查看人事工作台权限", status=403)

    try:
        context = _make_context(request)
        service = OverviewService()
        metrics = [
            service.get_metric(key, context)
            for key in (
                "active_headcount",
                "full_time_teacher",
                "double_teacher_valid",
                "new_join_ytd",
                "departure_ytd",
                "open_risk_count",
            )
        ]
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except HrProviderError as exc:
        logger.warning(str(exc))
        return _error(request, "PROVIDER_UNAVAILABLE", "部分指标暂时无法计算", status=503)

    body = _api_root(request)
    body["metrics"] = metrics
    return _json(request, body)


# ---------------------------------------------------------------------------
# HR01-04 队伍结构
# ---------------------------------------------------------------------------


@require_GET
def workforce_summary(request):
    """GET /api/hr/v1/home/workforce/summary —— 队伍结构结论卡。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.workforce.view")):
        return _error(request, "PERMISSION_DENIED", "无查看队伍结构权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.workforce_service import WorkforceService

        payload = WorkforceService().get_summary(context)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("workforce summary failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


@require_GET
def workforce_distribution(request):
    """GET /api/hr/v1/home/workforce/distribution?dimension=...（白名单）。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.workforce.view")):
        return _error(request, "PERMISSION_DENIED", "无查看队伍结构权限", status=403)

    dimension = request.GET.get("dimension", "")
    try:
        context = _make_context(request)
        from hr_control_center.services.workforce_service import WorkforceService

        payload = WorkforceService().get_distribution(context, dimension)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("workforce distribution failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


@require_GET
def workforce_org_comparison(request):
    """GET /api/hr/v1/home/workforce/org-comparison —— 学院/部门对比宽表。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.workforce.view")):
        return _error(request, "PERMISSION_DENIED", "无查看队伍结构权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.workforce_service import WorkforceService

        payload = WorkforceService().get_org_comparison(context)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("workforce comparison failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


# ---------------------------------------------------------------------------
# HR01-03 人事预警
# ---------------------------------------------------------------------------


@require_GET
def alert_list(request):
    """GET /api/hr/v1/home/alerts —— 预警列表（过滤/分页）。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.alert.view")):
        return _error(request, "PERMISSION_DENIED", "无查看人事预警权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.alert_service import AlertService

        filters = {
            "status": request.GET.get("status"),
            "severity": request.GET.get("severity"),
            "category": request.GET.get("category"),
            "overdue": request.GET.get("overdue"),
            "limit": request.GET.get("limit"),
            "offset": request.GET.get("offset"),
        }
        payload = AlertService().list_alerts(context, filters)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("alert list failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


@require_GET
def alert_summary(request):
    """GET /api/hr/v1/home/alerts/summary —— 预警统计。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.alert.view")):
        return _error(request, "PERMISSION_DENIED", "无查看人事预警权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.alert_service import AlertService

        payload = AlertService().get_summary(context)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("alert summary failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


def alert_run_rules(request):
    """
    POST /api/hr/v1/home/alerts/run-rules —— 触发预警规则扫描（幂等，去重）。
    运维触发动作，需 alert.manage 权限。
    """
    if request.method != "POST":
        return _error(
            request, "INVALID_REQUEST", "仅支持 POST", status=405
        )

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.alert.manage")):
        return _error(request, "PERMISSION_DENIED", "无管理人事预警权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.alert_service import AlertService

        payload = AlertService().run_rules(context)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("alert run rules failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "预警规则执行失败", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


# ---------------------------------------------------------------------------
# HR01-05 快捷办理
# ---------------------------------------------------------------------------


@require_GET
def quick_actions(request):
    """GET /api/hr/v1/home/quick-actions —— 已授权动作目录（服务端过滤）。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.quick_action.use")):
        return _error(request, "PERMISSION_DENIED", "无使用快捷办理权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.quick_action_service import QuickActionService

        payload = {"items": QuickActionService().get_catalog(context, request.user)}
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("quick actions failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


@require_GET
def todo_summary(request):
    """GET /api/hr/v1/home/todos/summary —— 待办统计。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.todo.view")):
        return _error(request, "PERMISSION_DENIED", "无查看待办权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.todo_service import TodoService

        payload = TodoService().get_summary(context)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except Exception:
        logger.exception("todo summary failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)


@require_GET
def todo_list(request):
    """GET /api/hr/v1/home/todos —— 待办列表（聚合分页）。"""
    try:
        _make_context(request)
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)

    if not (request.user.is_superuser or request.user.has_perm("hr.dashboard.todo.view")):
        return _error(request, "PERMISSION_DENIED", "无查看待办权限", status=403)

    try:
        context = _make_context(request)
        from hr_control_center.services.todo_service import TodoService

        page = int(request.GET.get("page", 1) or 1)
        page_size = int(request.GET.get("page_size", 20) or 20)
        page_size = min(max(page_size, 1), 100)
        payload = TodoService().list_todos(
            context,
            filters={
                "category": request.GET.get("category"),
                "severity": request.GET.get("severity"),
                "overdue": request.GET.get("overdue"),
            },
            page=page,
            page_size=page_size,
        )
    except HrContextError as exc:
        return _error(request, exc.code, exc.message, status=403)
    except (TypeError, ValueError):
        return _error(request, "INVALID_REQUEST", "分页参数无效", status=400)
    except Exception:
        logger.exception("todo list failed request=%s", _request_id(request))
        return _error(request, "INTERNAL_ERROR", "数据暂时无法计算", status=500)

    body = _api_root(request)
    body.update(payload)
    return _json(request, body)
