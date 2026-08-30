"""Tenant-scoped read models for the HR15 payroll control center."""
from django.db.models import Sum

from .authority_models import BenefitPlan, OccupationalPensionPlan
from .calculation_models import (
    PayrollCalculationBatch,
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
    PayrollPayslipFact,
    SalaryRuleVersion,
)
from .models import PayrollPeriod, PayrollProfile, PayrollResultFact
from .statutory_models import StatutoryContributionFact, StatutoryContributionRuleVersion


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    profiles = PayrollProfile.objects.filter(tenant_id=tenant_id)
    periods = PayrollPeriod.objects.filter(tenant_id=tenant_id)
    results = PayrollResultFact.objects.filter(tenant_id=tenant_id)
    rules = SalaryRuleVersion.objects.filter(tenant_id=tenant_id)
    calculations = PayrollCalculationBatch.objects.filter(tenant_id=tenant_id)
    payments = PayrollPaymentInstruction.objects.filter(tenant_id=tenant_id)
    payslips = PayrollPayslipFact.objects.filter(tenant_id=tenant_id)
    reconciliations = PayrollFinanceReconciliationFact.objects.filter(tenant_id=tenant_id)
    statutory_rules = StatutoryContributionRuleVersion.objects.filter(tenant_id=tenant_id)
    statutory_facts = StatutoryContributionFact.objects.filter(tenant_id=tenant_id)
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
            "publishedRules": rules.filter(status=SalaryRuleVersion.Status.PUBLISHED).count(),
            "completedCalculations": calculations.filter(
                status=PayrollCalculationBatch.Status.COMPLETED
            ).count(),
            "acceptedPayments": payments.filter(
                status=PayrollPaymentInstruction.Status.ACCEPTED
            ).count(),
            "publishedPayslips": payslips.count(),
            "reconciliationMismatches": reconciliations.filter(
                status=PayrollFinanceReconciliationFact.Status.MISMATCH
            ).count(),
            "publishedStatutoryRules": statutory_rules.filter(
                status=StatutoryContributionRuleVersion.Status.PUBLISHED
            ).count(),
            "sealedStatutoryContributions": statutory_facts.filter(
                status=StatutoryContributionFact.Status.SEALED
            ).count(),
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
        "recentRules": list(
            rules.order_by("priority", "item_code", "-version_no")[:50].values(
                "id",
                "rule_code",
                "version_no",
                "item_code",
                "name",
                "item_type",
                "currency_code",
                "status",
                "effective_from",
                "effective_to",
                "content_hash",
            )
        ),
        "recentCalculations": list(
            calculations.order_by("-created_at")[:20].values(
                "id",
                "payroll_period_id",
                "batch_no",
                "status",
                "staff_count",
                "result_count",
                "gross_total",
                "deduction_total",
                "net_total",
                "started_at",
                "completed_at",
            )
        ),
        "recentPayments": list(
            payments.order_by("-created_at")[:20].values(
                "id",
                "instruction_no",
                "payroll_result_id",
                "staff_id",
                "currency_code",
                "requested_amount",
                "status",
                "provider_code",
                "sent_at",
                "received_at",
            )
        ),
        "recentPayslips": list(
            payslips.order_by("-published_at")[:20].values(
                "id",
                "payslip_no",
                "payroll_result_id",
                "payment_instruction_id",
                "staff_id",
                "content_hash",
                "published_at",
            )
        ),
        "recentReconciliations": list(
            reconciliations.order_by("-reconciled_at")[:20].values(
                "id",
                "reconciliation_no",
                "payment_instruction_id",
                "expected_amount",
                "settled_amount",
                "difference_amount",
                "currency_code",
                "status",
                "reconciled_at",
            )
        ),
        "recentStatutoryContributions": list(
            statutory_facts.order_by("-created_at")[:50].values(
                "id",
                "payroll_period_id",
                "payroll_result_id",
                "staff_id",
                "contribution_group",
                "contribution_code",
                "contribution_base",
                "employee_amount",
                "employer_amount",
                "evidence_hash",
                "review_evidence_hash",
                "status",
                "sealed_at",
            )
        ),
        "capabilities": {
            "profile": True,
            "period": True,
            "resultFact": True,
            "finalization": True,
            "salaryItemRules": True,
            "fullCalculation": True,
            "allowanceBenefits": BenefitPlan.objects.filter(tenant_id=tenant_id).exists()
            or OccupationalPensionPlan.objects.filter(tenant_id=tenant_id).exists(),
            "socialInsuranceHousingFund": True,
            "payment": True,
            "financeReconciliation": True,
            "legacyReadReconcile": True,
            "legacyTakeover": False,
        },
    }
