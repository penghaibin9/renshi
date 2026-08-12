"""Tenant-scoped read models for HR16 retirement and exit."""
from collections import Counter

from .models import ExitCase, ExitEffect, ExitFact, RetirementFact


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    cases = ExitCase.objects.filter(tenant_id=tenant_id)
    effects = ExitEffect.objects.filter(tenant_id=tenant_id)
    exits = ExitFact.objects.filter(tenant_id=tenant_id)
    retirements = RetirementFact.objects.filter(tenant_id=tenant_id)
    counts = Counter(cases.values_list("status", flat=True))
    return {
        "summary": {
            "cases": cases.count(),
            "awaitingApproval": counts.get("SUBMITTED", 0),
            "handover": counts.get("HANDOVER", 0),
            "settlement": counts.get("SETTLEMENT", 0),
            "effectExceptions": effects.filter(status__in=["PARTIAL_FAILED", "FAILED"]).count(),
            "effectiveExits": exits.filter(status="EFFECTIVE").count(),
            "retirementFacts": retirements.filter(status="EFFECTIVE").count(),
        },
        "recentCases": list(
            cases.order_by("-updated_at")[:12].values(
                "id", "case_no", "person_id", "exit_type", "status", "requested_date",
                "last_working_date", "planned_employment_end_date", "planned_access_end_at", "updated_at"
            )
        ),
        "recentEffects": list(
            effects.order_by("-requested_at")[:12].values(
                "id", "case_id", "effect_version", "status", "hr03_status", "hr14_status",
                "iam_status", "settlement_status", "archive_status", "last_error", "requested_at",
                "applied_at", "reconciled_at"
            )
        ),
        "recentExitFacts": list(
            exits.order_by("-employment_end_date", "-created_at")[:12].values(
                "id", "fact_no", "person_id", "source_case_id", "exit_type", "employment_end_date",
                "last_working_date", "access_end_at", "status", "last_effect_error", "created_at"
            )
        ),
        "recentRetirements": list(
            retirements.order_by("-effective_date", "-created_at")[:12].values(
                "id", "fact_no", "person_id", "exit_fact_id", "retirement_type", "statutory_date",
                "effective_date", "pension_processing_status", "status", "created_at"
            )
        ),
        "capabilities": {
            "exitCase": True,
            "effectSaga": True,
            "exitFact": True,
            "retirementFact": True,
            "approvalWorkflow": False,
            "handoverChecklist": False,
            "retirementPolicy": False,
            "retirementPrecheck": False,
            "assetProvider": False,
            "iamProvider": False,
            "financeProvider": False,
            "archiveProvider": False,
        },
    }
