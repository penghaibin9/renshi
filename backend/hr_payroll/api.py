import json
import logging

from django.db import DatabaseError
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.utils import timezone

from base.auth_backends import get_allowed_company_ids
from hr_control_center.context import resolve_tenant_from_request

from .selectors import dashboard_snapshot
from .authority_registry import (
    PERM_BENEFIT_MANAGE,
    PERM_BENEFIT_VIEW,
    PERM_CALCULATE,
    PERM_CHANGE_APPROVE,
    PERM_CHANGE_MANAGE,
    PERM_CHANGE_VIEW,
    PERM_FINALIZE,
    PERM_INPUT_MANAGE,
    PERM_LEGACY_TAKEOVER_MANAGE,
    PERM_LEGACY_TAKEOVER_VIEW,
    PERM_PAYMENT,
    PERM_RECONCILE,
    PERM_REVIEW,
    PERM_RULE_MANAGE,
    PERM_STATUTORY_MANAGE,
    PERM_STATUTORY_VIEW,
)
from .authority_models import BenefitEnrollmentFact, BenefitPlan
from .calculation_models import SalaryRuleVersion
from .compensation_models import CompensationChangeCase
from .services.calculation_service import (
    PayrollCalculationError,
    PayrollCalculationService,
    PayrollRuleService,
)
from .services.finalization_service import (
    PayrollFinalizationError,
    PayrollFinalizationService,
)
from .services.payment_service import PayrollPaymentError, PayrollPaymentService
from .services.adjustment_service import PayrollAdjustmentError, PayrollAdjustmentService
from .services.legacy_reconciliation_service import LegacyPayrollReconciliationService
from .legacy_takeover_models import (
    LegacyPayrollAssetInventory,
    LegacyPayrollCutoverControl,
    LegacyPayrollWriteBlockAudit,
)
from .services.legacy_takeover_service import (
    LegacyPayrollTakeoverError,
    LegacyPayrollTakeoverService,
)
from .services.statutory_contribution_service import (
    StatutoryContributionError,
    StatutoryContributionRuleService,
)
from .services.compensation_change_service import (
    CompensationChangeError,
    CompensationChangeService,
)
from .services.benefit_pension_service import (
    BenefitPensionAuthorityService,
    PayrollAuthorityError,
)
from .statutory_models import StatutoryContributionFact, StatutoryContributionRuleVersion

READ_PERMISSION = "hr.payroll.view"
ADJUST_PERMISSION = "hr.payroll.adjust"
logger = logging.getLogger(__name__)


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


def _json_body(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayrollCalculationError("INVALID_JSON", "请求体必须是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise PayrollCalculationError("INVALID_JSON", "请求体必须是 JSON 对象")
    return payload


def _workflow_error(exc) -> JsonResponse:
    code = exc.code
    if code.endswith("_PROVIDER_UNAVAILABLE"):
        status = 503
    elif code.endswith("_PROVIDER_CONTRACT_INVALID"):
        status = 502
    elif code.endswith("_NOT_FOUND"):
        status = 404
    elif any(
        marker in code
        for marker in ("_CONFLICT", "_INVALID_STATE", "_NOT_FINAL", "_NOT_FROZEN", "_IN_PROGRESS")
    ):
        status = 409
    else:
        status = 400
    return _error(code, str(exc), status=status)


def _actor_id(request):
    return getattr(request.user, "id", None)


def _statutory_error(exc) -> JsonResponse:
    if exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif "CONFLICT" in exc.code or "OVERLAP" in exc.code or "INVALID_STATE" in exc.code:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def _statutory_rule_data(rule):
    return {
        "id": str(rule.id),
        "ruleCode": rule.rule_code,
        "versionNo": rule.version_no,
        "contributionGroup": rule.contribution_group,
        "contributionCode": rule.contribution_code,
        "name": rule.name,
        "jurisdictionCode": rule.jurisdiction_code,
        "baseVariableKey": rule.base_variable_key,
        "baseFloor": str(rule.base_floor),
        "baseCeiling": str(rule.base_ceiling),
        "employeeRate": str(rule.employee_rate),
        "employerRate": str(rule.employer_rate),
        "employeeItemCode": rule.employee_item_code,
        "employerItemCode": rule.employer_item_code,
        "effectiveFrom": str(rule.effective_from),
        "effectiveTo": str(rule.effective_to) if rule.effective_to else None,
        "policyEvidence": rule.policy_evidence_json,
        "contentHash": rule.content_hash,
        "status": rule.status,
    }


def _benefit_error(exc) -> JsonResponse:
    if exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif "CONFLICT" in exc.code or "STATE_INVALID" in exc.code:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def _compensation_change_error(exc) -> JsonResponse:
    if exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif any(
        marker in exc.code
        for marker in (
            "_CONFLICT",
            "_STATE_INVALID",
            "_SUPERSEDES_REQUIRED",
            "_MAKER_CHECKER_REQUIRED",
        )
    ):
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def _compensation_change_data(case):
    return {
        "id": str(case.id),
        "caseNo": case.case_no,
        "staffId": str(case.staff_id),
        "changeType": case.change_type,
        "changeTypeLabel": case.get_change_type_display(),
        "payrollVariableKey": case.payroll_variable_key,
        "itemName": case.item_name,
        "amountMode": case.amount_mode,
        "amountModeLabel": case.get_amount_mode_display(),
        "amount": str(case.amount),
        "currencyCode": case.currency_code,
        "prorationMode": case.proration_mode,
        "prorationModeLabel": case.get_proration_mode_display(),
        "effectiveFrom": str(case.effective_from),
        "effectiveTo": str(case.effective_to) if case.effective_to else None,
        "reviewDate": str(case.review_date) if case.review_date else None,
        "reasonCode": case.reason_code,
        "note": case.note,
        "sourceDomain": case.source_domain,
        "sourceRef": case.source_ref,
        "sourceVersion": case.source_version,
        "sourceSnapshot": case.source_snapshot_json,
        "evidenceRefs": case.evidence_refs_json,
        "supersedesCaseId": (
            str(case.supersedes_case_id) if case.supersedes_case_id else None
        ),
        "status": case.status,
        "statusLabel": case.get_status_display(),
        "contentHash": case.content_hash,
        "submittedBy": case.submitted_by,
        "submittedAt": case.submitted_at.isoformat() if case.submitted_at else None,
        "decidedBy": case.decided_by,
        "decidedAt": case.decided_at.isoformat() if case.decided_at else None,
        "decisionNote": case.decision_note,
    }


def compensation_changes(request):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = PERM_CHANGE_VIEW if request.method == "GET" else PERM_CHANGE_MANAGE
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    if request.method == "GET":
        try:
            rows = list(
                CompensationChangeCase.objects.filter(tenant_id=tenant_id).order_by(
                    "-effective_from", "-created_at"
                )[:500]
            )
        except DatabaseError:
            return _error(
                "COMPENSATION_CHANGE_STORAGE_UNAVAILABLE",
                "调资与津补贴数据表尚未完成升级，请稍后重试",
                status=503,
            )
        response = JsonResponse(
            {
                "data": [_compensation_change_data(row) for row in rows],
                "apiVersion": "1.0",
                "schemaVersion": "hr15.compensation-change.1",
            }
        )
        response["Cache-Control"] = "no-store"
        return response
    try:
        payload = _json_body(request)
        effective_from = parse_date(str(payload.get("effectiveFrom") or ""))
        effective_to_raw = payload.get("effectiveTo")
        review_date_raw = payload.get("reviewDate")
        effective_to = parse_date(str(effective_to_raw)) if effective_to_raw else None
        review_date = parse_date(str(review_date_raw)) if review_date_raw else None
        if (
            effective_from is None
            or (effective_to_raw and effective_to is None)
            or (review_date_raw and review_date is None)
        ):
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_DATE_INVALID", "日期必须使用 YYYY-MM-DD"
            )
        case = CompensationChangeService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).create_draft(
            case_no=payload.get("caseNo"),
            staff_id=payload.get("staffId"),
            change_type=payload.get("changeType"),
            payroll_variable_key=payload.get("payrollVariableKey"),
            item_name=payload.get("itemName"),
            amount_mode=payload.get("amountMode", "SET"),
            amount=payload.get("amount"),
            currency_code=payload.get("currencyCode", "CNY"),
            proration_mode=payload.get("prorationMode", "NONE"),
            effective_from=effective_from,
            effective_to=effective_to,
            review_date=review_date,
            reason_code=payload.get("reasonCode"),
            note=payload.get("note", ""),
            source_domain=payload.get("sourceDomain", ""),
            source_ref=payload.get("sourceRef", ""),
            source_version=payload.get("sourceVersion", ""),
            source_snapshot=payload.get("sourceSnapshot"),
            evidence_refs=payload.get("evidenceRefs"),
            supersedes_case_id=payload.get("supersedesCaseId"),
        )
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except CompensationChangeError as exc:
        return _compensation_change_error(exc)
    response = JsonResponse(
        {
            "data": _compensation_change_data(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.compensation-change.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def _decide_compensation_change(request, case_id, action):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = (
        PERM_CHANGE_MANAGE if action == "submit" else PERM_CHANGE_APPROVE
    )
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
        payload = _json_body(request)
        service = CompensationChangeService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        )
        if action == "submit":
            case = service.submit(case_id)
        elif action == "approve":
            case = service.approve(
                case_id, decision_note=payload.get("decisionNote", "")
            )
        else:
            case = service.reject(
                case_id, decision_note=payload.get("decisionNote", "")
            )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except CompensationChangeError as exc:
        return _compensation_change_error(exc)
    response = JsonResponse(
        {
            "data": _compensation_change_data(case),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.compensation-change.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def submit_compensation_change(request, case_id):
    return _decide_compensation_change(request, case_id, "submit")


def approve_compensation_change(request, case_id):
    return _decide_compensation_change(request, case_id, "approve")


def reject_compensation_change(request, case_id):
    return _decide_compensation_change(request, case_id, "reject")


def _benefit_plan_data(plan):
    return {
        "id": str(plan.id),
        "planCode": plan.plan_code,
        "versionNo": plan.version_no,
        "name": plan.name,
        "benefitType": plan.benefit_type,
        "providerName": plan.provider_name,
        "currencyCode": plan.currency_code,
        "employerRate": str(plan.employer_rate),
        "employeeRate": str(plan.employee_rate),
        "fixedAmount": str(plan.fixed_amount),
        "effectiveFrom": str(plan.effective_from),
        "effectiveTo": str(plan.effective_to) if plan.effective_to else None,
        "ruleSnapshot": plan.rule_snapshot_json,
        "contentHash": plan.content_hash,
        "status": plan.status,
    }


def _benefit_enrollment_data(enrollment):
    return {
        "id": str(enrollment.id),
        "enrollmentNo": enrollment.enrollment_no,
        "benefitPlanId": str(enrollment.benefit_plan_id),
        "staffId": str(enrollment.staff_id),
        "effectiveFrom": str(enrollment.effective_from),
        "effectiveTo": (
            str(enrollment.effective_to) if enrollment.effective_to else None
        ),
        "employerAmount": str(enrollment.employer_amount),
        "employeeAmount": str(enrollment.employee_amount),
        "snapshot": enrollment.snapshot_json,
        "supersedesEnrollmentId": (
            str(enrollment.supersedes_enrollment_id)
            if enrollment.supersedes_enrollment_id
            else None
        ),
    }


def benefit_plans(request):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = (
        PERM_BENEFIT_VIEW if request.method == "GET" else PERM_BENEFIT_MANAGE
    )
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    if request.method == "GET":
        plans = BenefitPlan.objects.filter(tenant_id=tenant_id).order_by(
            "plan_code", "-version_no"
        )
        response = JsonResponse(
            {
                "data": [_benefit_plan_data(plan) for plan in plans],
                "apiVersion": "1.0",
                "schemaVersion": "hr15.benefit-plan.1",
            }
        )
        response["Cache-Control"] = "no-store"
        return response
    try:
        payload = _json_body(request)
        effective_from = parse_date(str(payload.get("effectiveFrom") or ""))
        effective_to_raw = payload.get("effectiveTo")
        effective_to = (
            parse_date(str(effective_to_raw)) if effective_to_raw else None
        )
        if effective_from is None or (effective_to_raw and effective_to is None):
            raise PayrollAuthorityError(
                "EFFECTIVE_DATE_INVALID", "生效日期必须使用 YYYY-MM-DD"
            )
        rule_snapshot = payload.get("ruleSnapshot") or {}
        if not isinstance(rule_snapshot, dict):
            raise PayrollAuthorityError(
                "BENEFIT_PLAN_INPUT_INVALID", "规则快照必须是 JSON 对象"
            )
        plan = BenefitPensionAuthorityService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).create_benefit_plan(
            plan_code=payload.get("planCode"),
            version_no=payload.get("versionNo", 1),
            name=payload.get("name"),
            benefit_type=payload.get("benefitType"),
            provider_name=payload.get("providerName", ""),
            employer_rate=payload.get("employerRate", 0),
            employee_rate=payload.get("employeeRate", 0),
            fixed_amount=payload.get("fixedAmount", 0),
            effective_from=effective_from,
            effective_to=effective_to,
            rule_snapshot=rule_snapshot,
        )
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except PayrollAuthorityError as exc:
        return _benefit_error(exc)
    response = JsonResponse(
        {
            "data": _benefit_plan_data(plan),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.benefit-plan.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def publish_benefit_plan(request, plan_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_BENEFIT_MANAGE
        )
        plan = BenefitPensionAuthorityService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).publish_benefit_plan(plan_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollAuthorityError as exc:
        return _benefit_error(exc)
    response = JsonResponse(
        {
            "data": _benefit_plan_data(plan),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.benefit-plan.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def benefit_enrollments(request):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = (
        PERM_BENEFIT_VIEW if request.method == "GET" else PERM_BENEFIT_MANAGE
    )
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    if request.method == "GET":
        rows = BenefitEnrollmentFact.objects.filter(tenant_id=tenant_id).order_by(
            "-effective_from", "-created_at"
        )[:500]
        response = JsonResponse(
            {
                "data": [_benefit_enrollment_data(row) for row in rows],
                "apiVersion": "1.0",
                "schemaVersion": "hr15.benefit-enrollment.1",
            }
        )
        response["Cache-Control"] = "no-store"
        return response
    try:
        payload = _json_body(request)
        effective_from = parse_date(str(payload.get("effectiveFrom") or ""))
        effective_to_raw = payload.get("effectiveTo")
        effective_to = (
            parse_date(str(effective_to_raw)) if effective_to_raw else None
        )
        if effective_from is None or (effective_to_raw and effective_to is None):
            raise PayrollAuthorityError(
                "EFFECTIVE_DATE_INVALID", "生效日期必须使用 YYYY-MM-DD"
            )
        snapshot = payload.get("snapshot") or {}
        if not isinstance(snapshot, dict):
            raise PayrollAuthorityError(
                "BENEFIT_ENROLLMENT_INPUT_INVALID", "办理依据必须是 JSON 对象"
            )
        enrollment = BenefitPensionAuthorityService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).enroll_benefit(
            enrollment_no=payload.get("enrollmentNo"),
            plan_id=payload.get("benefitPlanId"),
            staff_id=payload.get("staffId"),
            effective_from=effective_from,
            effective_to=effective_to,
            employer_amount=payload.get("employerAmount", 0),
            employee_amount=payload.get("employeeAmount", 0),
            snapshot=snapshot,
            supersedes_enrollment_id=payload.get("supersedesEnrollmentId"),
        )
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except PayrollAuthorityError as exc:
        return _benefit_error(exc)
    response = JsonResponse(
        {
            "data": _benefit_enrollment_data(enrollment),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.benefit-enrollment.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def statutory_rules(request):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = PERM_STATUTORY_VIEW if request.method == "GET" else PERM_STATUTORY_MANAGE
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    if request.method == "GET":
        rows = StatutoryContributionRuleVersion.objects.filter(tenant_id=tenant_id).order_by(
            "contribution_group", "contribution_code", "-version_no"
        )
        response = JsonResponse(
            {
                "data": [_statutory_rule_data(row) for row in rows],
                "apiVersion": "1.0",
                "schemaVersion": "hr15.statutory-rule.1",
            }
        )
        response["Cache-Control"] = "no-store"
        return response
    try:
        payload = _json_body(request)
        effective_from = parse_date(str(payload.get("effectiveFrom", "")))
        effective_to_raw = payload.get("effectiveTo")
        effective_to = parse_date(str(effective_to_raw)) if effective_to_raw else None
        if effective_from is None or (effective_to_raw and effective_to is None):
            raise StatutoryContributionError(
                "STATUTORY_EFFECTIVE_DATE_INVALID", "effective dates must use YYYY-MM-DD"
            )
        rule = StatutoryContributionRuleService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).create_draft(
            rule_code=payload.get("ruleCode"),
            version_no=payload.get("versionNo"),
            contribution_group=payload.get("contributionGroup"),
            contribution_code=payload.get("contributionCode"),
            name=payload.get("name"),
            jurisdiction_code=payload.get("jurisdictionCode"),
            base_variable_key=payload.get("baseVariableKey"),
            base_floor=payload.get("baseFloor"),
            base_ceiling=payload.get("baseCeiling"),
            employee_rate=payload.get("employeeRate"),
            employer_rate=payload.get("employerRate"),
            employee_item_code=payload.get("employeeItemCode"),
            employer_item_code=payload.get("employerItemCode"),
            effective_from=effective_from,
            effective_to=effective_to,
            policy_evidence=payload.get("policyEvidence"),
        )
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except StatutoryContributionError as exc:
        return _statutory_error(exc)
    response = JsonResponse(
        {
            "data": _statutory_rule_data(rule),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.statutory-rule.1",
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    return response


def publish_statutory_rule(request, rule_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_STATUTORY_MANAGE)
        rule = StatutoryContributionRuleService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).publish(rule_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except StatutoryContributionError as exc:
        return _statutory_error(exc)
    response = JsonResponse(
        {
            "data": _statutory_rule_data(rule),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.statutory-rule.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def statutory_contributions(request, result_id):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_STATUTORY_VIEW)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    rows = StatutoryContributionFact.objects.filter(
        tenant_id=tenant_id, payroll_result_id=result_id
    ).order_by("contribution_group", "contribution_code")
    data = [
        {
            "id": str(row.id),
            "payrollResultId": str(row.payroll_result_id),
            "staffId": str(row.staff_id),
            "contributionGroup": row.contribution_group,
            "contributionCode": row.contribution_code,
            "requestedBase": str(row.requested_base),
            "contributionBase": str(row.contribution_base),
            "employeeRate": str(row.employee_rate),
            "employerRate": str(row.employer_rate),
            "employeeAmount": str(row.employee_amount),
            "employerAmount": str(row.employer_amount),
            "evidenceHash": row.evidence_hash,
            "reviewEvidenceHash": row.review_evidence_hash,
            "status": row.status,
        }
        for row in rows
    ]
    response = JsonResponse(
        {
            "data": data,
            "apiVersion": "1.0",
            "schemaVersion": "hr15.statutory-contribution.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def dashboard(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    try:
        data = dashboard_snapshot(tenant_id)
    except DatabaseError:
        logger.exception("hr15_dashboard_storage_unavailable tenant_id=%s", tenant_id)
        return _error(
            "PAYROLL_STORAGE_UNAVAILABLE",
            "薪酬数据存储暂不可用，请确认数据库升级状态后重试",
            status=503,
        )
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


def legacy_reconciliation(request):
    """Read-only double-read report; legacy payroll is never promoted to authority."""
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    raw_limit = request.GET.get("limit", "200")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return _error("INVALID_LIMIT", "limit 必须是整数", status=400)

    data = LegacyPayrollReconciliationService(tenant_id).snapshot(limit=limit)
    data.update(
        {
            "apiVersion": "1.0",
            "schemaVersion": "hr15.legacy-reconciliation.1",
            "generatedAt": timezone.now().isoformat(),
        }
    )
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response


def _legacy_inventory_data(inventory):
    if inventory is None:
        return None
    return {
        "id": str(inventory.id),
        "inventoryNo": inventory.inventory_no,
        "status": inventory.status,
        "legacyRowCount": inventory.legacy_row_count,
        "matchedRowCount": inventory.matched_row_count,
        "unavailableRowCount": inventory.unavailable_row_count,
        "snapshotHash": inventory.snapshot_hash,
        "reasonCodes": inventory.reason_codes_json,
        "capturedAt": inventory.captured_at.isoformat(),
    }


def _legacy_control_data(control):
    if control is None:
        return None
    return {
        "id": str(control.id),
        "status": control.status,
        "latestInventoryId": (
            str(control.latest_inventory_id) if control.latest_inventory_id else None
        ),
        "latestSnapshotHash": control.latest_snapshot_hash,
        "writeBlockEnabled": control.write_block_enabled,
        "activationEvidenceHash": control.activation_evidence_hash,
        "activationEvidence": control.activation_evidence_json,
        "verifiedAt": control.verified_at.isoformat() if control.verified_at else None,
        "activatedAt": control.activated_at.isoformat() if control.activated_at else None,
    }


def _legacy_takeover_error(exc):
    if exc.code.endswith("_NOT_FOUND"):
        status = 404
    elif "UNAVAILABLE" in exc.code or "STALE" in exc.code:
        status = 422
    elif "CONFLICT" in exc.code or "ALREADY_ACTIVE" in exc.code:
        status = 409
    else:
        status = 400
    return _error(exc.code, str(exc), status=status)


def legacy_takeover_inventories(request):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = (
        PERM_LEGACY_TAKEOVER_VIEW
        if request.method == "GET"
        else PERM_LEGACY_TAKEOVER_MANAGE
    )
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)

    if request.method == "GET":
        control = LegacyPayrollCutoverControl.objects.filter(tenant_id=tenant_id).first()
        inventory = None
        if control and control.latest_inventory_id:
            inventory = LegacyPayrollAssetInventory.objects.filter(
                tenant_id=tenant_id, id=control.latest_inventory_id
            ).first()
        response = JsonResponse(
            {
                "data": {
                    "control": _legacy_control_data(control),
                    "latestInventory": _legacy_inventory_data(inventory),
                },
                "apiVersion": "1.0",
                "schemaVersion": "hr15.legacy-takeover.1",
            }
        )
        response["Cache-Control"] = "no-store"
        return response

    try:
        payload = _json_body(request)
        outcome = LegacyPayrollTakeoverService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).capture_inventory(inventory_no=payload.get("inventoryNo", ""))
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except LegacyPayrollTakeoverError as exc:
        return _legacy_takeover_error(exc)
    response = JsonResponse(
        {
            "data": {
                "inventory": _legacy_inventory_data(outcome.inventory),
                "created": outcome.created,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.legacy-takeover.1",
        },
        status=201 if outcome.created else 200,
    )
    response["Cache-Control"] = "no-store"
    return response


def activate_legacy_takeover(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_LEGACY_TAKEOVER_MANAGE
        )
        payload = _json_body(request)
        control = LegacyPayrollTakeoverService(
            tenant_id,
            actor_user_id=_actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).activate(
            inventory_id=payload.get("inventoryId"),
            activation_key=payload.get("activationKey", ""),
            evidence=payload.get("evidence"),
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    except LegacyPayrollTakeoverError as exc:
        return _legacy_takeover_error(exc)
    response = JsonResponse(
        {
            "data": _legacy_control_data(control),
            "apiVersion": "1.0",
            "schemaVersion": "hr15.legacy-takeover.1",
        }
    )
    response["Cache-Control"] = "no-store"
    return response


def legacy_write_block_audits(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(
            request, required_permission=PERM_LEGACY_TAKEOVER_VIEW
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    rows = LegacyPayrollWriteBlockAudit.objects.filter(tenant_id=tenant_id).order_by(
        "-blocked_at"
    )[:100]
    response = JsonResponse(
        {
            "data": [
                {
                    "id": str(row.id),
                    "operation": row.operation,
                    "objectRefHash": row.object_ref_hash,
                    "reasonCode": row.reason_code,
                    "blockedAt": row.blocked_at.isoformat(),
                }
                for row in rows
            ],
            "apiVersion": "1.0",
            "schemaVersion": "hr15.legacy-write-block-audit.1",
        }
    )
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


def salary_rules(request):
    if request.method not in {"GET", "POST"}:
        return _error("METHOD_NOT_ALLOWED", status=405)
    permission = READ_PERMISSION if request.method == "GET" else PERM_RULE_MANAGE
    try:
        tenant_id = resolve_request_tenant(request, required_permission=permission)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    if request.method == "GET":
        rows = list(
            SalaryRuleVersion.objects.filter(tenant_id=tenant_id)
            .order_by("priority", "item_code", "-version_no")
            .values(
                "id",
                "rule_code",
                "version_no",
                "item_code",
                "name",
                "item_type",
                "priority",
                "currency_code",
                "formula_json",
                "dependencies_json",
                "rounding_mode",
                "effective_from",
                "effective_to",
                "content_hash",
                "status",
                "published_at",
            )[:200]
        )
        response = JsonResponse(
            {"data": rows, "apiVersion": "1.0", "schemaVersion": "hr15.salary-rule.1"}
        )
        response["Cache-Control"] = "no-store"
        return response
    try:
        payload = _json_body(request)
        effective_from = parse_date(str(payload.get("effectiveFrom", "")))
        effective_to_raw = payload.get("effectiveTo")
        effective_to = parse_date(str(effective_to_raw)) if effective_to_raw else None
        if effective_from is None or (effective_to_raw and effective_to is None):
            raise PayrollCalculationError(
                "SALARY_RULE_DATE_INVALID", "生效日期必须是 YYYY-MM-DD"
            )
        rule = PayrollRuleService(tenant_id, _actor_id(request)).create_draft(
            rule_code=payload.get("ruleCode"),
            version_no=payload.get("versionNo", 1),
            item_code=payload.get("itemCode"),
            name=payload.get("name"),
            item_type=payload.get("itemType"),
            formula=payload.get("formula"),
            dependencies=payload.get("dependencies"),
            priority=payload.get("priority", 100),
            currency_code=payload.get("currencyCode", "CNY"),
            rounding_mode=payload.get("roundingMode", "HALF_UP"),
            effective_from=effective_from,
            effective_to=effective_to,
        )
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {"id": str(rule.id), "ruleCode": rule.rule_code, "status": rule.status},
            "apiVersion": "1.0",
            "schemaVersion": "hr15.salary-rule.1",
        },
        status=201,
    )


def publish_salary_rule(request, rule_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_RULE_MANAGE)
        rule = PayrollRuleService(tenant_id, _actor_id(request)).publish(rule_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(rule.id),
                "ruleCode": rule.rule_code,
                "status": rule.status,
                "contentHash": rule.content_hash,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.salary-rule.1",
        }
    )


def capture_period_input(request, period_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_INPUT_MANAGE)
        payload = _json_body(request)
        forbidden = sorted(
            {"sourceVersions", "variables", "currencyCode"}.intersection(payload)
        )
        if forbidden:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_CLIENT_AUTHORITY_FORBIDDEN",
                "authoritative payroll input is collected only from trusted providers: "
                + ",".join(forbidden),
            )
        snapshot = PayrollCalculationService(
            tenant_id,
            _actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).capture_input(
            period_id=period_id,
            staff_id=payload.get("staffId"),
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except (PayrollCalculationError, ValueError) as exc:
        if isinstance(exc, ValueError) and not hasattr(exc, "code"):
            exc = PayrollCalculationError("PAYROLL_INPUT_STAFF_INVALID", "staffId 必须是 UUID")
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(snapshot.id),
                "periodId": str(snapshot.payroll_period_id),
                "staffId": str(snapshot.staff_id),
                "snapshotVersion": snapshot.snapshot_version,
                "contentHash": snapshot.content_hash,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.input-snapshot.2",
        },
        status=201,
    )


def calculate_period(request, period_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_CALCULATE)
        payload = _json_body(request)
        outcome = PayrollCalculationService(
            tenant_id,
            _actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).calculate(
            period_id=period_id,
            batch_no=payload.get("batchNo", ""),
            idempotency_key=request.headers.get("Idempotency-Key")
            or payload.get("idempotencyKey", ""),
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {
                "batchId": str(outcome.batch.id),
                "status": outcome.batch.status,
                "resultIds": list(outcome.result_ids),
                "staffCount": outcome.batch.staff_count,
                "netTotal": str(outcome.batch.net_total),
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.calculation.1",
        },
        status=201,
    )


def review_result(request, result_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_REVIEW)
        payload = _json_body(request)
        fact = PayrollCalculationService(tenant_id, _actor_id(request)).review_result(
            result_id=result_id,
            decision=payload.get("decision", ""),
            note=payload.get("note", ""),
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {"id": str(fact.id), "decision": fact.decision},
            "apiVersion": "1.0",
            "schemaVersion": "hr15.review.1",
        },
        status=201,
    )


def complete_period_review(request, period_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_REVIEW)
        period = PayrollCalculationService(
            tenant_id,
            _actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).complete_review(period_id=period_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {"periodId": str(period.id), "status": period.status},
            "apiVersion": "1.0",
            "schemaVersion": "hr15.review-completion.1",
        }
    )


def finalize_period(request, period_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_FINALIZE)
        outcome = PayrollFinalizationService(tenant_id).finalize_period(period_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollFinalizationError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {
                "periodId": str(outcome.period.id),
                "status": outcome.period.status,
                "resultIds": list(outcome.finalized_result_ids),
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.finalization.1",
        }
    )


def create_payment(request, result_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_PAYMENT)
        payload = _json_body(request)
        instruction = PayrollPaymentService(
            tenant_id, _actor_id(request)
        ).create_instruction(
            result_id=result_id,
            instruction_no=payload.get("instructionNo", ""),
            provider_code=payload.get("providerCode", ""),
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollPaymentError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(instruction.id),
                "instructionNo": instruction.instruction_no,
                "status": instruction.status,
                "requestedAmount": str(instruction.requested_amount),
                "currencyCode": instruction.currency_code,
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.payment.1",
        },
        status=201,
    )


def send_payment(request, instruction_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_PAYMENT)
        instruction = PayrollPaymentService(
            tenant_id,
            _actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).dispatch(instruction_id=instruction_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollPaymentError as exc:
        return _workflow_error(exc)
    return JsonResponse({"data": {"id": str(instruction.id), "status": instruction.status}})


def receive_payment(request, instruction_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        resolve_request_tenant(request, required_permission=PERM_PAYMENT)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    return _error(
        "PAYROLL_PAYMENT_TRUSTED_RECEIPT_REQUIRED",
        "payment receipts are accepted only from a trusted provider worker",
        status=403,
    )


def publish_payslip(request, result_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_PAYMENT)
        payload = _json_body(request)
        payslip = PayrollPaymentService(
            tenant_id,
            _actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).publish_payslip(result_id=result_id, payslip_no=payload.get("payslipNo", ""))
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollPaymentError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {"id": str(payslip.id), "contentHash": payslip.content_hash},
            "apiVersion": "1.0",
            "schemaVersion": "hr15.payslip.1",
        },
        status=201,
    )


def reconcile_payment(request, instruction_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_RECONCILE)
        payload = _json_body(request)
        fact = PayrollPaymentService(
            tenant_id,
            _actor_id(request),
            correlation_id=request.headers.get("X-Correlation-ID", ""),
        ).reconcile(
            instruction_id=instruction_id,
            reconciliation_no=payload.get("reconciliationNo", ""),
        )
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollPaymentError as exc:
        return _workflow_error(exc)
    return JsonResponse(
        {
            "data": {
                "id": str(fact.id),
                "status": fact.status,
                "differenceAmount": str(fact.difference_amount),
            },
            "apiVersion": "1.0",
            "schemaVersion": "hr15.reconciliation.1",
        },
        status=201,
    )
