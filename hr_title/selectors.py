"""Tenant-scoped read models for the HR13 professional-title workspace."""

from __future__ import annotations

from collections import Counter

from .models import (
    ProfessionalTitleResult,
    TitleAppealRecord,
    TitleApplicationCase,
    TitleMaterialSnapshot,
    TitlePolicyVersion,
    TitlePublicityRecord,
    TitleQualificationDecision,
    TitleReviewAssignment,
    TitleReviewBallot,
    TitleReviewRound,
)


def _tenant(tenant_id: int) -> int:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    return int(tenant_id)


def dashboard_snapshot(tenant_id: int) -> dict:
    tenant_id = _tenant(tenant_id)
    cases = TitleApplicationCase.objects.filter(tenant_id=tenant_id)
    policies = TitlePolicyVersion.objects.filter(tenant_id=tenant_id)
    materials = TitleMaterialSnapshot.objects.filter(tenant_id=tenant_id)
    qualifications = TitleQualificationDecision.objects.filter(tenant_id=tenant_id)
    review_rounds = TitleReviewRound.objects.filter(tenant_id=tenant_id)
    assignments = TitleReviewAssignment.objects.filter(tenant_id=tenant_id)
    ballots = TitleReviewBallot.objects.filter(tenant_id=tenant_id)
    publicities = TitlePublicityRecord.objects.filter(tenant_id=tenant_id)
    appeals = TitleAppealRecord.objects.filter(tenant_id=tenant_id)
    results = ProfessionalTitleResult.objects.filter(tenant_id=tenant_id)

    status_counts = Counter(cases.values_list("status", flat=True))
    return {
        "summary": {
            "policyVersions": policies.count(),
            "applications": cases.count(),
            "qualificationDecisions": qualifications.count(),
            "materials": materials.count(),
            "acceptedMaterials": materials.filter(
                status=TitleMaterialSnapshot.Status.ACCEPTED
            ).count(),
            "reviewRounds": review_rounds.count(),
            "openReviewRounds": review_rounds.filter(
                status=TitleReviewRound.Status.OPEN
            ).count(),
            "reviewAssignments": assignments.count(),
            "reviewBallots": ballots.count(),
            "publicityRecords": publicities.count(),
            "openPublicities": publicities.filter(
                status=TitlePublicityRecord.Status.OPEN
            ).count(),
            "appeals": appeals.count(),
            "openAppeals": appeals.filter(status=TitleAppealRecord.Status.OPEN).count(),
            "upheldAppeals": appeals.filter(status=TitleAppealRecord.Status.UPHELD).count(),
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
        "recentQualificationDecisions": list(
            qualifications.order_by("-decided_at", "-created_at")[:12].values(
                "id",
                "decision_no",
                "application_case_id",
                "attempt_no",
                "decision",
                "reason_code",
                "reason",
                "decided_by",
                "decided_at",
            )
        ),
        "recentMaterials": list(
            materials.order_by("-updated_at")[:12].values(
                "id",
                "material_no",
                "application_case_id",
                "material_type",
                "display_name",
                "source_domain",
                "source_ref",
                "source_version",
                "content_hash",
                "status",
                "supersedes_snapshot_id",
                "updated_at",
            )
        ),
        "recentReviewRounds": list(
            review_rounds.order_by("-opened_at", "-created_at")[:12].values(
                "id",
                "round_no",
                "application_case_id",
                "attempt_no",
                "required_ballots",
                "required_pass_votes",
                "status",
                "opened_by",
                "opened_at",
                "closed_by",
                "closed_at",
                "closure_snapshot_json",
            )
        ),
        "recentReviewAssignments": list(
            assignments.order_by("-assigned_at", "-created_at")[:24].values(
                "id",
                "assignment_no",
                "review_round_id",
                "reviewer_staff_id",
                "reviewer_role",
                "status",
                "conflict_declared",
                "conflict_note",
                "assigned_by",
                "assigned_at",
                "responded_at",
            )
        ),
        "recentReviewBallots": list(
            ballots.order_by("-submitted_at", "-created_at")[:24].values(
                "id",
                "ballot_no",
                "review_round_id",
                "assignment_id",
                "recommendation",
                "score",
                "rationale",
                "submitted_by",
                "submitted_at",
            )
        ),
        "recentPublicities": list(
            publicities.order_by("-created_at")[:12].values(
                "id",
                "publicity_no",
                "application_case_id",
                "start_at",
                "end_at",
                "content_snapshot_json",
                "status",
                "opened_by",
                "closed_by",
                "closed_at",
                "cancelled_at",
                "created_at",
            )
        ),
        "recentAppeals": list(
            appeals.order_by("-created_at")[:24].values(
                "id",
                "appeal_no",
                "publicity_id",
                "application_case_id",
                "appellant_ref",
                "reason",
                "evidence_json",
                "status",
                "resolution",
                "resolved_by",
                "resolved_at",
                "created_at",
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
            "qualificationReview": True,
            "materials": True,
            "expertPanel": True,
            "deliberationVote": True,
            "publicity": True,
            "appealReview": True,
        },
    }
