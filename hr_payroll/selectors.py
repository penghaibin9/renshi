"""Tenant-scoped read models for the HR15 payroll control center."""
from django.db.models import Sum

from .models import PayrollPeriod, PayrollProfile, PayrollResultFact


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    profiles = PayrollProfile.objects.filter(tenant_id=tenant_id)
    periods = PayrollPeriod.objects.filter(tenant_id=tenant_id)
    results = PayrollResultFact.objects.filter(tenant_id=tenant_id)
    latest = periods.order_by("-end_date", "-created_at").first()
    latest_results = results.none() if latest is None else results.filter(payroll_period_id=latest.id)
    net = None
    if latest is not None:
        amount = latest_results.filter(status__in=["FINALIZED", "ADJUSTED"]).aggregate(v=Sum("net_amount"))["v"]
        net = None if amount is None else str(amount)
    return {
        "summary": {
            "activeProfiles": profiles.filter(status="ACTIVE").count(),
            "periods": periods.count(),
            "openPeriods": periods.exclude(status__in=["FINALIZED", "CLOSED"]).count(),
            "finalizedResults": results.filter(status__in=["FINALIZED", "ADJUSTED"]).count(),
            "latestPeriodCode": getattr(latest, "period_code", None),
            "latestPeriodStatus": getattr(latest, "status", None),
            "latestPeriodNet": net,
        },
        "recentPeriods": list(
            periods.order_by("-end_date")[:12].values(
                "id", "period_code", "start_date", "end_date", "status", "finalized_at"
            )
        ),
        "recentResults": list(
            results.order_by("-created_at")[:12].values(
                "id", "result_no", "payroll_period_id", "staff_id", "currency_code",
                "gross_amount", "deduction_amount", "net_amount", "status", "created_at"
            )
        ),
        "recentProfiles": list(
            profiles.order_by("-effective_from", "-created_at")[:12].values(
                "id", "staff_id", "payroll_identity_no", "pay_group_code", "currency_code",
                "effective_from", "effective_to", "status"
            )
        ),
        "capabilities": {
            "profile": True,
            "period": True,
            "resultFact": True,
            "finalization": True,
            "salaryItemRules": False,
            "fullCalculation": False,
            "allowanceBenefits": False,
            "socialInsuranceHousingFund": False,
            "payment": False,
            "financeReconciliation": False,
            "legacyReadReconcile": True,
            "legacyTakeover": False,
        },
    }
