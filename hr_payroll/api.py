import json

from django.http import JsonResponse
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .services.adjustment_service import PayrollAdjustmentError, PayrollAdjustmentService

READ_PERMISSION = "hr.payroll.view"
ADJUST_PERMISSION = "hr.payroll.adjust"


class HrPayrollAccessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_request_tenant(request, *, required_permission: str = READ_PERMISSION) -> int:
    if not getattr(request.user, "is_authenticated", False):
        raise HrPayrollAccessError("AUTHENTICATION_REQUIRED", "authentication required")
    tenant_id = resolve_tenant_from_request(request)
    if not tenant_id:
        raise HrPayrollAccessError("TENANT_CONTEXT_REQUIRED", "请选择当前学校")
    tenant_id = int(tenant_id)
    if not request.user.is_superuser:
        allowed = {int(x) for x in get_allowed_company_ids(request.user)}
        if tenant_id not in allowed:
            raise HrPayrollAccessError("TENANT_ACCESS_DENIED", "当前账号无权访问该学校")
        if not request.user.has_perm(required_permission):
            raise HrPayrollAccessError(
                "PERMISSION_DENIED", f"缺少权限: {required_permission}"
            )
    return tenant_id


def _error(code: str, message: str = "", *, status: int) -> JsonResponse:
    response = JsonResponse({"error": {"code": code, "message": message}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def dashboard(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    data = dashboard_snapshot(tenant_id)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr15.workspace.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def adjust_result(request, source_result_id):
    """Append one retroactive payroll delta fact; never rewrite the source fact."""
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=ADJUST_PERMISSION
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error("INVALID_JSON", "请求体必须是合法 JSON", status=400)
    if not isinstance(payload, dict):
        return _error("INVALID_JSON", "请求体必须是 JSON 对象", status=400)

    try:
        outcome = PayrollAdjustmentService(tenant_id).append_adjustment(
            source_result_id=source_result_id,
            adjustment_no=payload.get("adjustmentNo", ""),
            gross_delta=payload.get("grossDelta"),
            deduction_delta=payload.get("deductionDelta"),
            net_delta=payload.get("netDelta"),
            currency_code=payload.get("currencyCode"),
        )
    except PayrollAdjustmentError as exc:
        if exc.code == "PAYROLL_SOURCE_RESULT_NOT_FOUND":
            status = 404
        elif exc.code in {
            "PAYROLL_ADJUSTMENT_IDEMPOTENCY_CONFLICT",
            "PAYROLL_SOURCE_RESULT_NOT_FINAL",
            "PAYROLL_PERIOD_NOT_FINAL",
            "PAYROLL_ADJUSTMENT_CURRENCY_MISMATCH",
        }:
            status = 409
        else:
            status = 400
        return _error(exc.code, str(exc), status=status)

    fact = outcome.adjustment
    response = JsonResponse(
        {
            "data": {
                "id": str(fact.id),
                "resultNo": fact.result_no,
                "sourceResultId": str(fact.supersedes_result_id),
                "payrollPeriodId": str(fact.payroll_period_id),
                "staffId": str(fact.staff_id),
                "currencyCode": fact.currency_code,
                "grossDelta": str(fact.gross_amount),
                "deductionDelta": str(fact.deduction_amount),
                "netDelta": str(fact.net_amount),
                "status": fact.status,
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.adjustment.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response
