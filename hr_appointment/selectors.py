"""Tenant-scoped read models for the HR14 appointment workspace."""
from collections import Counter

from .models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentPolicyVersion,
    AppointmentPublicityObjection,
    AppointmentPublicityRecord,
    AppointmentQuotaPool,
    AppointmentRankingResult,
    PositionAppointmentFact,
)


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    cases = AppointmentApplicationCase.objects.filter(tenant_id=tenant_id)
    batches = AppointmentBatch.objects.filter(tenant_id=tenant_id)
    policies = AppointmentPolicyVersion.objects.filter(tenant_id=tenant_id)
    facts = PositionAppointmentFact.objects.filter(tenant_id=tenant_id)
    rankings = AppointmentRankingResult.objects.filter(tenant_id=tenant_id)
    publicities = AppointmentPublicityRecord.objects.filter(tenant_id=tenant_id)
    objections = AppointmentPublicityObjection.objects.filter(tenant_id=tenant_id)
    quota_pools = AppointmentQuotaPool.objects.filter(
        tenant_id=tenant_id, batch__tenant_id=tenant_id
    ).select_related("batch")
    counts = Counter(cases.values_list("status", flat=True))
    quota_total = sum(row.available for row in quota_pools.iterator())
    quota_rows = list(quota_pools.order_by("-updated_at")[:12])
    unresolved_objections = objections.filter(
        status__in=[
            AppointmentPublicityObjection.Status.RECEIVED,
            AppointmentPublicityObjection.Status.UNDER_REVIEW,
        ]
    )
    return {
        "summary": {
            "policyVersions": policies.count(),
            "competitionBatches": batches.count(),
            "applications": cases.count(),
            "awaitingReview": counts.get("ELIGIBLE", 0) + counts.get("UNDER_REVIEW", 0),
            "rankingResults": rankings.count(),
            "selectedRankings": rankings.filter(outcome=AppointmentRankingResult.Outcome.SELECTED).count(),
            "proposed": counts.get("PROPOSED", 0),
            "inPublicity": counts.get("PUBLICITY", 0),
            "openPublicities": publicities.filter(status=AppointmentPublicityRecord.Status.OPEN).count(),
            "closedPublicities": publicities.filter(status=AppointmentPublicityRecord.Status.CLOSED).count(),
            "publicityObjections": objections.count(),
            "unresolvedObjections": unresolved_objections.count(),
            "upheldObjections": objections.filter(status=AppointmentPublicityObjection.Status.UPHELD).count(),
            "effectiveAppointments": facts.filter(status="EFFECTIVE").count(),
            "quotaPools": quota_pools.count(),
            "availableQuota": quota_total,
        },
        "recentApplications": list(
            cases.order_by("-updated_at")[:12].values(
                "id", "case_no", "person_id", "position_instance_id", "batch_no",
                "requested_level_code", "status", "updated_at"
            )
        ),
        "recentBatches": list(
            batches.order_by("-updated_at")[:12].values(
                "id", "batch_no", "name", "business_type", "policy_version_id",
                "application_from", "application_to", "publicity_from", "publicity_to",
                "status", "updated_at"
            )
        ),
        "recentRankings": list(
            rankings.order_by("batch_no", "position_instance_id", "rank_no", "-finalized_at")[:24].values(
                "id", "ranking_no", "application_case_id", "batch_no",
                "position_instance_id", "attempt_no", "total_score", "rank_no",
                "outcome", "score_snapshot_json", "finalized_by", "finalized_at"
            )
        ),
        "recentPublicities": list(
            publicities.order_by("-opened_at")[:16].values(
                "id", "publicity_no", "application_case_id", "ranking_result_id",
                "batch_no", "person_id", "position_instance_id", "attempt_no",
                "start_at", "end_at", "status", "opened_by", "opened_at",
                "closed_by", "closed_at", "cancellation_reason"
            )
        ),
        "recentObjections": list(
            objections.order_by("-submitted_at")[:24].values(
                "id", "objection_no", "publicity_id", "submitter_ref", "content_summary",
                "evidence_refs_json", "status", "submitted_at", "resolved_by",
                "resolved_at", "resolution_note"
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
        "recentQuotaPools": [
            {
                "id": row.id,
                "batchNo": row.batch.batch_no,
                "categoryCode": row.category_code,
                "levelGroupCode": row.level_group_code,
                "exactLevelCode": row.exact_level_code,
                "authorized": row.authorized,
                "occupied": row.occupied,
                "reserved": row.reserved,
                "exceptionQuota": row.exception_quota,
                "available": row.available,
                "version": row.version,
            }
            for row in quota_rows
        ],
        "capabilities": {
            "policy": True,
            "application": True,
            "appointmentFact": True,
            "quotaSnapshot": True,
            "competition": True,
            "reviewRanking": True,
            "publicity": True,
            "publicityObjection": True,
            "termChange": False,
        },
    }
