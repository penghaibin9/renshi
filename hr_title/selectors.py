"""Tenant-scoped read models for the HR13 professional-title workspace."""

from __future__ import annotations

from collections import Counter

from .models import ProfessionalTitleResult, TitleApplicationCase, TitlePolicyVersion


def _tenant(tenant_id: int) -> int:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    return int(tenant_id)


def dashboard_snapshot(tenant_id: int) -> dict:
    tenant_id = _tenant(tenant_id)
    cases = TitleApplicationCase.objects.filter(tenant_id=tenant_id)
    policies = TitlePolicyVersion.objects.filter(tenant_id=tenant_id)
    results = ProfessionalTitleResult.objects.filter(tenant_id=tenant_id)

    status_counts = Counter(cases.values_list("status", flat=True))
    return {
        "summary": {
            "policyVersions": policies.count(),
            "applications": cases.count(),
            "awaitingQualification": status_counts.get("SUBMITTED", 0),
            "underReview": status_counts.get("UNDER_REVIEW", 0),
            "inPublicity": status_counts.get("PUBLICITY", 0),
            "effectiveResults": results.filter(status="EFFECTIVE").count(),
        },
        "statusBreakdown": dict(status_counts),
        "recentApplications": list(
            cases.order_by("-updated_at")[:12].values(
                "id",
                "case_no",
                "person_id",
                "batch_no",
                "requested_title_name",
                "requested_title_code",
                "status",
                "submitted_at",
                "updated_at",
            )
        ),
        "recentResults": list(
            results.order_by("-effective_from", "-created_at")[:12].values(
                "id",
                "result_no",
                "person_id",
                "title_code",
                "title_name",
                "title_series_code",
                "title_level_code",
                "effective_from",
                "effective_to",
                "status",
                "created_at",
            )
        ),
        "recentPolicies": list(
            policies.order_by("-effective_from", "-version_no")[:8].values(
                "id",
                "policy_code",
                "name",
                "version_no",
                "status",
                "title_series_code",
                "title_level_code",
                "effective_from",
                "effective_to",
            )
        ),
        "capabilities": {
            "policy": True,
            "application": True,
            "formalResult": True,
            "qualificationReview": False,
            "materials": False,
            "expertPanel": False,
            "deliberationVote": False,
            "publicity": False,
            "appealReview": False,
        },
    }
