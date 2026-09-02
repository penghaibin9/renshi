"""Tenant-scoped HR15 profile and payroll-period setup APIs."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils.dateparse import parse_date

from hr_payroll.api import HrPayrollAccessError, _error, _json_body, resolve_request_tenant
from hr_payroll.authority_registry import PERM_INPUT_MANAGE
from hr_payroll.authority_models import BenefitPlan
from hr_payroll.calculation_models import SalaryRuleVersion
from hr_payroll.compensation_models import CompensationChangeCase
from hr_payroll.models import PayrollPeriod, PayrollProfile
from hr_payroll.services.calculation_service import PayrollCalculationError
from hr_payroll.services.period_service import PayrollPeriodError, PayrollPeriodService
from hr_staff.models import HrStaffMaster


def setup_options(request):
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    staff = HrStaffMaster.objects.filter(tenant_id=tenant_id).select_related("person_id").order_by("staff_no")[:1000]
    profiles = PayrollProfile.objects.filter(tenant_id=tenant_id, status=PayrollProfile.Status.ACTIVE).order_by("payroll_identity_no")
    periods = PayrollPeriod.objects.filter(tenant_id=tenant_id).order_by("-start_date")
    benefit_plans = BenefitPlan.objects.filter(tenant_id=tenant_id).order_by(
        "plan_code", "-version_no"
    )
    input_rules = SalaryRuleVersion.objects.filter(
        tenant_id=tenant_id,
        status=SalaryRuleVersion.Status.PUBLISHED,
    ).order_by("priority", "item_code", "-version_no")
    try:
        compensation_cases = list(
            CompensationChangeCase.objects.filter(tenant_id=tenant_id).order_by(
                "-effective_from", "case_no"
            )
        )
        compensation_changes_available = True
    except DatabaseError:
        compensation_cases = []
        compensation_changes_available = False
    labels = {str(item.id): f"{item.person_id.legal_name} · {item.staff_no}" for item in staff}
    return JsonResponse({"data": {
        "staff": [{"value": str(item.id), "label": labels[str(item.id)]} for item in staff],
        "profiles": [{"staffId": str(item.staff_id), "label": f"{labels.get(str(item.staff_id), '教职工')} · {item.payroll_identity_no}"} for item in profiles],
        "periods": [{"value": str(item.id), "label": f"{item.period_code} · {item.start_date} 至 {item.end_date}", "status": item.status} for item in periods],
        "benefitPlans": [
            {
                "value": str(item.id),
                "label": f"{item.name} · {item.plan_code} v{item.version_no}",
                "status": item.status,
            }
            for item in benefit_plans
        ],
        "compensationChangeTypes": [
            {"value": value, "label": label}
            for value, label in CompensationChangeCase.ChangeType.choices
        ],
        "compensationAmountModes": [
            {"value": value, "label": label}
            for value, label in CompensationChangeCase.AmountMode.choices
        ],
        "compensationProrationModes": [
            {"value": value, "label": label}
            for value, label in CompensationChangeCase.ProrationMode.choices
        ],
        "payrollVariables": [
            {
                "value": str(item.formula_json.get("key")),
                "label": f"{item.name} · {item.formula_json.get('key')}",
            }
            for item in input_rules
            if str(item.formula_json.get("op", "")).upper() == "INPUT"
            and item.formula_json.get("key")
        ],
        "supersedableCompensationChanges": [
            {
                "value": str(item.id),
                "label": (
                    f"{item.case_no} · {item.item_name} · "
                    f"{labels.get(str(item.staff_id), '教职工')}"
                ),
            }
            for item in compensation_cases
            if item.status == CompensationChangeCase.Status.APPROVED
        ],
        "compensationChanges": [
            {
                "value": str(item.id),
                "label": (
                    f"{item.case_no} · {item.item_name} · "
                    f"{labels.get(str(item.staff_id), '教职工')}"
                ),
                "status": item.status,
                "submittedBy": item.submitted_by,
            }
            for item in compensation_cases
        ],
        "compensationChangesAvailable": compensation_changes_available,
    }})


def create_profile(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_INPUT_MANAGE)
        body = _json_body(request)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _error(exc.code, str(exc), status=400)
    identity = str(body.get("payrollIdentityNo") or "").strip()
    pay_group = str(body.get("payGroupCode") or "").strip().upper()
    currency = str(body.get("currencyCode") or "CNY").strip().upper()
    effective_from = parse_date(str(body.get("effectiveFrom") or ""))
    effective_to = parse_date(str(body.get("effectiveTo") or "")) if body.get("effectiveTo") else None
    if not identity or not pay_group or len(currency) != 3 or not effective_from or (effective_to and effective_to <= effective_from):
        return _error("PAYROLL_PROFILE_INPUT_INVALID", "请选择本校人员并填写有效薪酬身份、工资组、币种和生效日期", status=400)
    try:
        with transaction.atomic():
            staff = HrStaffMaster.objects.select_for_update().filter(
                id=body.get("staffId"),
                tenant_id=tenant_id,
            ).first()
            if staff is None:
                return _error(
                    "PAYROLL_PROFILE_INPUT_INVALID",
                    "请选择当前学校的教职工",
                    status=400,
                )
            profiles = PayrollProfile.objects.select_for_update().filter(
                tenant_id=tenant_id,
                staff_id=staff.id,
                status=PayrollProfile.Status.ACTIVE,
            )
            overlap = profiles.filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=effective_from)
            )
            if effective_to:
                overlap = overlap.filter(effective_from__lt=effective_to)
            if overlap.exists():
                return _error(
                    "PAYROLL_PROFILE_OVERLAP",
                    "该人员已有重叠的有效薪酬档案",
                    status=409,
                )
            profile = PayrollProfile(
                tenant_id=tenant_id,
                staff_id=staff.id,
                payroll_identity_no=identity,
                pay_group_code=pay_group,
                currency_code=currency,
                payment_account_ref=str(body.get("paymentAccountRef") or "").strip(),
                effective_from=effective_from,
                effective_to=effective_to,
                created_by=getattr(request.user, "id", None),
                updated_by=getattr(request.user, "id", None),
            )
            profile.full_clean()
            profile.save()
    except ValidationError:
        return _error(
            "PAYROLL_PROFILE_INPUT_INVALID",
            "薪酬档案数据不符合约束，请检查编号、工资组、币种和日期",
            status=400,
        )
    except IntegrityError:
        return _error("PAYROLL_PROFILE_IDENTITY_CONFLICT", "薪酬身份编号已存在", status=409)
    return JsonResponse({"data": {"id": str(profile.id), "status": profile.status}}, status=201)


def create_period(request):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_INPUT_MANAGE)
        body = _json_body(request)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollCalculationError as exc:
        return _error(exc.code, str(exc), status=400)
    code = str(body.get("periodCode") or "").strip().upper()
    start_date = parse_date(str(body.get("startDate") or ""))
    end_date = parse_date(str(body.get("endDate") or ""))
    if not code or not start_date or not end_date or end_date <= start_date:
        return _error("PAYROLL_PERIOD_INPUT_INVALID", "请填写有效期间编号和起止日期", status=400)
    try:
        with transaction.atomic():
            periods = PayrollPeriod.objects.select_for_update().filter(
                tenant_id=tenant_id
            )
            if periods.filter(
                start_date__lte=end_date,
                end_date__gte=start_date,
            ).exists():
                return _error(
                    "PAYROLL_PERIOD_OVERLAP",
                    "工资期间与已有期间重叠",
                    status=409,
                )
            period = PayrollPeriod(
                tenant_id=tenant_id,
                period_code=code,
                start_date=start_date,
                end_date=end_date,
                created_by=getattr(request.user, "id", None),
                updated_by=getattr(request.user, "id", None),
            )
            period.full_clean()
            period.save()
    except ValidationError:
        return _error(
            "PAYROLL_PERIOD_INPUT_INVALID",
            "工资期间数据不符合约束，请检查期间编号和起止日期",
            status=400,
        )
    except IntegrityError:
        return _error("PAYROLL_PERIOD_CODE_CONFLICT", "工资期间编号已存在", status=409)
    return JsonResponse({"data": {"id": str(period.id), "status": period.status}}, status=201)


def freeze_period_input(request, period_id):
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant_id = resolve_request_tenant(request, required_permission=PERM_INPUT_MANAGE)
        period = PayrollPeriodService(tenant_id, getattr(request.user, "id", None)).freeze_input(period_id)
    except HrPayrollAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except PayrollPeriodError as exc:
        status = 404 if exc.code.endswith("NOT_FOUND") else 409
        return _error(exc.code, str(exc), status=status)
    return JsonResponse({"data": {"id": str(period.id), "status": period.status}})
