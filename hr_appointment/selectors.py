"""Tenant-scoped read models for the HR14 appointment workspace."""
from collections import Counter

from .models import AppointmentApplicationCase, AppointmentPolicyVersion, PositionAppointmentFact


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    cases = AppointmentApplicationCase.objects.filter(tenant_id=tenant_id)
    policies = AppointmentPolicyVersion.objects.filter(tenant_id=tenant_id)
    facts = PositionAppointmentFact.objects.filter(tenant_id=tenant_id)
    counts = Counter(cases.values_list("status", flat=True))
    return {
        "summary": {
            "policyVersions": policies.count(),
            "applications": cases.count(),
            "awaitingReview": counts.get("ELIGIBLE", 0) + counts.get("UNDER_REVIEW", 0),
            "proposed": counts.get("PROPOSED", 0),
            "inPublicity": counts.get("PUBLICITY", 0),
            "effectiveAppointments": facts.filter(status="EFFECTIVE").count(),
        },
        "recentApplications": list(
            cases.order_by("-updated_at")[:12].values(
                "id", "case_no", "person_id", "position_instance_id", "batch_no",
                "requested_level_code", "status", "updated_at"
            )
        ),
        "recentAppointments": list(
            facts.order_by("-effective_from", "-created_at")[:12].values(
                "id", "appointment_no", "person_id", "position_instance_id",
                "application_case_id", "level_code", "effective_from", "effective_to",
                "status", "created_at"
            )
        ),
        "recentPolicies": list(
            policies.order_by("-effective_from", "-version_no")[:8].values(
                "id", "policy_code", "name", "version_no", "status",
                "position_category", "level_code", "effective_from", "effective_to"
            )
        ),
        "capabilities": {
            "policy": True,
            "application": True,
            "appointmentFact": True,
            "quotaSnapshot": False,
            "competition": False,
            "reviewRanking": False,
            "publicity": False,
            "termChange": False,
        },
    }
