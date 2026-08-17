"""
hr_onboarding/api/views.py

HR05 管理端 JSON API（统一 /api/hr/v1/onboarding/）。
S3：cases 列表/详情、confirm-intent/request-delay/decline。
S4-S7 陆续挂载 activation/materials/tasks/probations。
"""

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from hr_onboarding.api import base as api_base
from hr_onboarding.api import selectors
from hr_onboarding.api.exceptions import Hr05ApiError, NotFoundError
from hr_onboarding.constants import HR05_ERROR_CODES, HR05_EVENT_TYPES
from hr_onboarding.models import HrOnboardingCase
from hr_onboarding.permissions import HR05_PERMISSIONS, require_hr05_permission
from hr_onboarding.services.case_service import CaseService


@require_GET
def hr05_api_health(request):
    """健康探针：envelope 自检 + tenant fail-closed。"""
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    return api_base.ok(request, {"status": "OK", "tenant_id": context.tenant_id})


@require_GET
def hr05_api_contract(request):
    """契约自检：schemaVersion / 权限码 / 错误码 / 事件类型。"""
    return api_base.ok(
        request,
        {
            "apiVersion": api_base.API_VERSION,
            "schemaVersion": api_base.SCHEMA_VERSION,
            "permissions": sorted(HR05_PERMISSIONS),
            "errorCodes": sorted(HR05_ERROR_CODES),
            "eventTypes": sorted(HR05_EVENT_TYPES),
        },
    )


@require_GET
@require_hr05_permission("hr05.case.view")
def hr05_cases_list(request):
    """待报到/全部 case 列表（tenant 隔离 + DB 分页）。"""
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    try:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("pageSize", 20))
    except (TypeError, ValueError):
        page, page_size = 1, 20
    data = selectors.list_cases(
        tenant_id=context.tenant_id,
        status=request.GET.get("status") or None,
        keyword=request.GET.get("keyword", ""),
        page=page,
        page_size=min(page_size, 100),
    )
    return api_base.ok(request, data)


@require_GET
@require_hr05_permission("hr05.case.view")
def hr05_case_detail(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
    detail = selectors.get_case_detail(tenant_id=context.tenant_id, case_id=case_id)
    if detail is None:
        return api_base.handle_hr05_error(request, NotFoundError("case 不存在或无权访问"))
    return api_base.ok(request, detail)


def _load_case_or_404(context, case_id: str):
    try:
        case = HrOnboardingCase.objects.filter(
            tenant_id=context.tenant_id, id=case_id
        ).first()
    except (ValueError, TypeError):
        case = None
    if case is None:
        raise NotFoundError("case 不存在或无权访问")
    return case


@require_GET
@require_hr05_permission("hr05.case.view")
def hr05_case_activation_gate(request, case_id: str):
    """Activation Gate 检查（只读实时，禁止过期缓存，05 §39）。"""
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        from django.utils.dateparse import parse_date

        effective_at = request.GET.get("effective_at")
        effective = parse_date(effective_at) if effective_at else context.today()
        if effective is None:
            raise Hr05ApiError("effective_at 格式非法")
        from hr_onboarding.services.activation_service import ActivationService

        gate = ActivationService(tenant_id=context.tenant_id).gate(case, effective_at=effective)
        return api_base.ok(
            request,
            {
                "passed": gate.passed,
                "items": [
                    {"code": i.code, "label": i.label, "ok": i.ok, "detail": i.detail}
                    for i in gate.items
                ],
            },
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.case.activate")
@csrf_exempt
def hr05_case_activate(request, case_id: str):
    """执行正式生效（ActivateOnboardingCase 领域命令，幂等）。"""
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        from django.utils.dateparse import parse_date

        effective_at = request.POST.get("effective_at") or request.GET.get("effective_at")
        effective = parse_date(effective_at) if effective_at else context.today()
        if effective is None:
            raise Hr05ApiError("effective_at 格式非法")
        idem_key = api_base.get_idempotency_key(request)
        if not idem_key:
            raise Hr05ApiError("缺少 Idempotency-Key（写操作必须幂等）")

        from hr_onboarding.services.activation_service import ActivationService

        result = ActivationService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).activate(case, effective_at=effective, idempotency_key=idem_key)
        return api_base.ok(request, result)
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.report.checkin")
@csrf_exempt
def hr05_case_report(request, case_id: str):
    """确认报到（幂等：同 case+时间 返回原记录）。"""
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        from django.utils.dateparse import parse_datetime

        actual_report_at = request.POST.get("actual_report_at")
        if not actual_report_at:
            raise Hr05ApiError("actual_report_at 必填")
        parsed = parse_datetime(actual_report_at)
        if parsed is None:
            raise Hr05ApiError("actual_report_at 格式非法（ISO datetime）")

        from hr_onboarding.services.report_service import ReportService

        checkin = ReportService(
            tenant_id=context.tenant_id, actor_user_id=context.user_id
        ).confirm_report(
            case,
            actual_report_at=parsed,
            location=request.POST.get("location", ""),
            checked_identity=request.POST.get("checked_identity") in ("true", "1", "on"),
            notes=request.POST.get("notes", ""),
            now=context.now(),  # 学校时区基准
        )
        return api_base.ok(
            request,
            {
                "case_id": case_id,
                "checkin_id": str(checkin.id),
                "actual_report_at": checkin.actual_report_at.isoformat(),
                "case_status": "REPORTED",
            },
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.case.view")
@csrf_exempt
def hr05_case_confirm_intent(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        service = CaseService(
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
        )
        service.confirm_intent(case)
        return api_base.ok(
            request, {"case_id": case_id, "status": "PREPARING"}
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.case.view")
@csrf_exempt
def hr05_case_request_delay(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        new_date = request.POST.get("new_date") or (request.GET.get("new_date"))
        reason = request.POST.get("reason", "")
        if not new_date:
            raise Hr05ApiError("new_date 必填")
        from django.utils.dateparse import parse_date

        parsed = parse_date(new_date)
        if parsed is None:
            raise Hr05ApiError("new_date 格式非法")
        service = CaseService(tenant_id=context.tenant_id, actor_user_id=context.user_id)
        delay = service.request_delay(case, new_date=parsed, reason=reason)
        return api_base.ok(
            request,
            {"case_id": case_id, "delay_id": str(delay.id), "status": "REPORT_DELAYED"},
        )
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)


@require_POST
@require_hr05_permission("hr05.case.cancel")
@csrf_exempt
def hr05_case_decline(request, case_id: str):
    try:
        context = api_base.make_hr05_context(request)
        case = _load_case_or_404(context, case_id)
        service = CaseService(tenant_id=context.tenant_id, actor_user_id=context.user_id)
        service.decline(case, reason=request.POST.get("reason", ""))
        return api_base.ok(request, {"case_id": case_id, "status": "DECLINED"})
    except Hr05ApiError as exc:
        return api_base.handle_hr05_error(request, exc)
