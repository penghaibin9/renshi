"""Tenant-scoped read models for the HR15 payroll control center."""
import logging

from django.db import DatabaseError
from django.db.models import Sum
from hr_staff.models import HrStaffMaster

from .authority_models import (
    BenefitEnrollmentFact,
    BenefitPlan,
)
from .calculation_models import (
    PayrollCalculationBatch,
    PayrollFinanceReconciliationFact,
    PayrollPaymentInstruction,
    PayrollPayslipFact,
    SalaryRuleVersion,
)
from .models import (
    ExternalSettlementBasisInput,
    PayrollPeriod,
    PayrollProfile,
    PayrollResultFact,
)
from .compensation_models import CompensationChangeCase
from .legacy_takeover_models import LegacyPayrollCutoverControl
from .statutory_models import StatutoryContributionFact, StatutoryContributionRuleVersion


logger = logging.getLogger(__name__)


def _external_settlement_snapshot(tenant_id: int) -> tuple[int, list[dict], bool]:
    """Keep the core payroll workspace readable during a rolling migration.

    External settlement intake was added after the core HR15 tables.  A deployment
    may briefly run new application code before migration 0011 has reached every
    database.  That optional read must fail closed without erasing the already
    authoritative profile, period and payroll-result facts from the dashboard.
    """

    try:
        inputs = ExternalSettlementBasisInput.objects.filter(tenant_id=tenant_id)
        count = inputs.count()
        recent = list(
            inputs.order_by("-received_at")[:50].values(
                "id",
                "source_domain",
                "source_engagement_id",
                "source_version",
                "period_code",
                "verified_workload",
                "policy_ref",
                "content_hash",
                "received_at",
            )
        )
    except DatabaseError as exc:
        logger.warning(
            "hr15_external_settlement_intake_unavailable tenant_id=%s error=%s",
            tenant_id,
            exc,
        )
        return 0, [], False
    return count, recent, True


def _compensation_change_snapshot(tenant_id: int) -> tuple[int, int, list[dict], bool]:
    """Read the optional change ledger without breaking a rolling deployment."""

    try:
        cases = CompensationChangeCase.objects.filter(tenant_id=tenant_id)
        count = cases.count()
        pending = cases.filter(status=CompensationChangeCase.Status.SUBMITTED).count()
        recent = list(
            cases.order_by("-effective_from", "-created_at")[:50].values(
                "id",
                "case_no",
                "staff_id",
                "change_type",
                "payroll_variable_key",
                "item_name",
                "amount_mode",
                "amount",
                "currency_code",
                "proration_mode",
                "effective_from",
                "effective_to",
                "review_date",
                "reason_code",
                "supersedes_case_id",
                "status",
                "submitted_by",
                "submitted_at",
                "decided_by",
                "decided_at",
            )
        )
        staff_ids = {item["staff_id"] for item in recent}
        labels = {
            row.id: f"{row.person_id.legal_name} · {row.staff_no}"
            for row in HrStaffMaster.objects.filter(
                tenant_id=tenant_id, id__in=staff_ids
            ).select_related("person_id")
        }
        for item in recent:
            item["staff_name"] = labels.get(item["staff_id"], "人员档案暂不可用")
    except DatabaseError as exc:
        logger.warning(
            "hr15_compensation_change_unavailable tenant_id=%s error=%s",
            tenant_id,
            exc,
        )
        return 0, 0, [], False
    return count, pending, recent, True


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
    benefit_plans = BenefitPlan.objects.filter(tenant_id=tenant_id)
    benefit_enrollments = BenefitEnrollmentFact.objects.filter(tenant_id=tenant_id)
    (
        compensation_change_count,
        pending_compensation_change_count,
        recent_compensation_changes,
        compensation_change_available,
    ) = _compensation_change_snapshot(tenant_id)
    (
        external_settlement_input_count,
        recent_external_settlement_inputs,
        external_settlement_available,
    ) = _external_settlement_snapshot(tenant_id)
    legacy_cutover = LegacyPayrollCutoverControl.objects.filter(tenant_id=tenant_id).first()
    latest = periods.order_by("-end_date", "-created_at").first()
    latest_results = results.none() if latest is None else results.filter(payroll_period_id=latest.id)
    net = None
    if latest is not None:
        amount = latest_results.filter(status__in=["FINALIZED", "ADJUSTED"]).aggregate(v=Sum("net_amount"))["v"]
        net = None if amount is None else str(amount)
    recent_benefit_enrollments = list(
        benefit_enrollments.order_by("-effective_from", "-created_at")[:50].values(
            "id",
            "enrollment_no",
            "benefit_plan_id",
            "staff_id",
            "effective_from",
            "effective_to",
            "employer_amount",
            "employee_amount",
            "supersedes_enrollment_id",
        )
    )
    enrollment_staff_ids = {
        item["staff_id"] for item in recent_benefit_enrollments
    }
    enrollment_staff_labels = {
        row.id: f"{row.person_id.legal_name} · {row.staff_no}"
        for row in HrStaffMaster.objects.filter(
            tenant_id=tenant_id, id__in=enrollment_staff_ids
        ).select_related("person_id")
    }
    for item in recent_benefit_enrollments:
        item["staff_name"] = enrollment_staff_labels.get(
            item["staff_id"], "人员档案暂不可用"
        )
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
            "benefitPlans": benefit_plans.count(),
            "publishedBenefitPlans": benefit_plans.filter(
                status=BenefitPlan.Status.PUBLISHED
            ).count(),
            "benefitEnrollments": benefit_enrollments.count(),
            "compensationChanges": compensation_change_count,
            "pendingCompensationChanges": pending_compensation_change_count,
            "sealedStatutoryContributions": statutory_facts.filter(
                status=StatutoryContributionFact.Status.SEALED
            ).count(),
            "externalSettlementInputs": external_settlement_input_count,
            "legacyTakeoverStatus": getattr(legacy_cutover, "status", None),
            "legacyWriteBlockEnabled": bool(
                getattr(legacy_cutover, "write_block_enabled", False)
            ),
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
        "recentBenefitPlans": list(
            benefit_plans.order_by("plan_code", "-version_no")[:50].values(
                "id",
                "plan_code",
                "version_no",
                "name",
                "benefit_type",
                "provider_name",
                "currency_code",
                "employer_rate",
                "employee_rate",
                "fixed_amount",
                "effective_from",
                "effective_to",
                "content_hash",
                "status",
            )
        ),
        "recentBenefitEnrollments": recent_benefit_enrollments,
        "recentCompensationChanges": recent_compensation_changes,
        "recentExternalSettlementInputs": recent_external_settlement_inputs,
        "capabilities": {
            "profile": True,
            "period": True,
            "resultFact": True,
            "finalization": True,
            "salaryItemRules": True,
            "fullCalculation": True,
            "allowanceBenefits": compensation_change_available,
            "socialInsuranceHousingFund": True,
            "payment": True,
            "financeReconciliation": True,
            "legacyReadReconcile": True,
            "legacyTakeover": True,
            "externalSettlementIntake": external_settlement_available,
        },
        "capabilityReasons": {
            "allowanceBenefits": (
                None
                if compensation_change_available
                else "调资与津补贴变更单尚未完成数据库升级，当前禁止新增或审批。"
            ),
            "externalSettlementIntake": (
                None
                if external_settlement_available
                else "校外人员结算依据尚未完成数据库升级，当前禁止接收或推断该类输入。"
            )
        },
    }
