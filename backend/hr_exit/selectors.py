"""Tenant-scoped read models for HR16 retirement and exit."""
from collections import Counter
import logging

from django.conf import settings
from django.db import DatabaseError

from .evidence_upload import is_private_evidence_ref
from .models import (
    ExitCase,
    ExitEffect,
    ExitFact,
    ExitHandoverItem,
    RetirementFact,
    RetirementPolicy,
    RetirementPrecheck,
)


logger = logging.getLogger(__name__)

_RETIREMENT_POLICY_FIELDS = (
    "id",
    "policy_code",
    "version_no",
    "status",
    "retirement_type",
    "gender_code",
    "staff_category_code",
    "relationship_type",
    "special_condition_code",
    "retirement_age_months",
    "transition_birth_start",
    "delay_step_birth_months",
    "max_retirement_age_months",
    "minimum_service_months",
    "effective_from",
    "effective_to",
    "priority",
    "rationale",
    "content_hash",
    "updated_at",
)
_RETIREMENT_POLICY_COHORT_FIELDS = {
    "transition_birth_start",
    "delay_step_birth_months",
    "max_retirement_age_months",
}


def _external_provider_ready(participant: str) -> bool:
    configured = getattr(settings, "HR16_EXIT_EXTERNAL_PROVIDERS", {}) or {}
    item = configured.get(participant, {}) if isinstance(configured, dict) else {}
    return bool(
        isinstance(item, dict)
        and str(item.get("url", "") or "").strip()
        and str(item.get("token", "") or "").strip()
    )


def _retirement_policy_snapshot(tenant_id: int) -> tuple[int, list[dict], bool]:
    """Read legacy policy columns when the cohort-policy migration is pending."""

    policies = RetirementPolicy.objects.filter(tenant_id=tenant_id)
    try:
        active_count = policies.filter(status="ACTIVE").count()
        recent = list(
            policies.order_by("-updated_at")[:20].values(*_RETIREMENT_POLICY_FIELDS)
        )
        return active_count, recent, True
    except DatabaseError as exc:
        logger.warning(
            "hr16_retirement_cohort_policy_unavailable tenant_id=%s error=%s",
            tenant_id,
            exc,
        )

    # Policies from migration 0009 remain useful as read-only evidence. Do not
    # advertise maintenance or precheck until the cohort fields from 0012 exist.
    legacy_fields = tuple(
        field
        for field in _RETIREMENT_POLICY_FIELDS
        if field not in _RETIREMENT_POLICY_COHORT_FIELDS
    )
    try:
        policies = RetirementPolicy.objects.filter(tenant_id=tenant_id)
        active_count = policies.filter(status="ACTIVE").count()
        recent = list(policies.order_by("-updated_at")[:20].values(*legacy_fields))
    except DatabaseError as exc:
        logger.warning(
            "hr16_retirement_policy_storage_unavailable tenant_id=%s error=%s",
            tenant_id,
            exc,
        )
        return 0, [], False
    for item in recent:
        for field in _RETIREMENT_POLICY_COHORT_FIELDS:
            item[field] = None
    return active_count, recent, False


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    cases = ExitCase.objects.filter(tenant_id=tenant_id)
    effects = ExitEffect.objects.filter(tenant_id=tenant_id)
    exits = ExitFact.objects.filter(tenant_id=tenant_id)
    superseded_exit_ids = exits.exclude(
        supersedes_fact_id__isnull=True
    ).values_list("supersedes_fact_id", flat=True)
    current_exits = exits.exclude(id__in=superseded_exit_ids)
    retirements = RetirementFact.objects.filter(tenant_id=tenant_id)
    handover_items = ExitHandoverItem.objects.filter(tenant_id=tenant_id)
    retirement_prechecks = RetirementPrecheck.objects.filter(tenant_id=tenant_id)
    (
        active_retirement_policy_count,
        recent_retirement_policies,
        retirement_policy_available,
    ) = _retirement_policy_snapshot(tenant_id)
    required_handover = handover_items.filter(required=True)
    counts = Counter(cases.values_list("status", flat=True))
    recent_handover_items = list(
        handover_items.order_by("case_id", "status", "due_date", "created_at")[:24].values(
            "id", "item_no", "case_id", "category_code", "title", "required",
            "owner_staff_id", "due_date", "status", "evidence_ref", "completed_by",
            "completed_at", "waiver_reason", "supersedes_item_id", "updated_at"
        )
    )
    for item in recent_handover_items:
        private_evidence = is_private_evidence_ref(item.get("evidence_ref", ""))
        item["has_evidence"] = private_evidence
        item["evidence_download_url"] = (
            f"/api/v1/hr/exit/handover-items/{item['id']}/evidence/download/"
            if private_evidence
            else ""
        )
        if private_evidence:
            item["evidence_ref"] = ""
    return {
        "summary": {
            "cases": cases.count(),
            "awaitingApproval": counts.get("SUBMITTED", 0),
            "approved": counts.get("APPROVED", 0),
            "returned": counts.get("RETURNED", 0),
            "rejected": counts.get("REJECTED", 0),
            "handover": counts.get("HANDOVER", 0),
            "settlement": counts.get("SETTLEMENT", 0),
            "handoverItems": handover_items.count(),
            "pendingRequiredHandover": required_handover.filter(status="PENDING").count(),
            "completedRequiredHandover": required_handover.filter(status="COMPLETED").count(),
            "waivedRequiredHandover": required_handover.filter(status="WAIVED").count(),
            "effectExceptions": effects.filter(status__in=["PARTIAL_FAILED", "FAILED"]).count(),
            "effectiveExits": current_exits.filter(
                status__in=(ExitFact.Status.EFFECTIVE, ExitFact.Status.REVISED)
            ).count(),
            "revokedExits": current_exits.filter(
                status=ExitFact.Status.REVOKED
            ).count(),
            "retirementFacts": retirements.filter(status="EFFECTIVE").count(),
            "activeRetirementPolicies": active_retirement_policy_count,
            "retirementPrechecks": retirement_prechecks.count(),
        },
        "recentCases": list(
            cases.order_by("-updated_at")[:12].values(
                "id", "case_no", "person_id", "exit_type", "status", "requested_date",
                "last_working_date", "planned_employment_end_date", "planned_access_end_at", "updated_at"
            )
        ),
        "recentHandoverItems": recent_handover_items,
        "recentEffects": list(
            effects.order_by("-requested_at")[:12].values(
                "id", "case_id", "effect_version", "status", "hr03_status", "hr07_status",
                "hr14_status", "iam_status", "asset_status", "settlement_status",
                "finance_status", "archive_status", "last_error", "requested_at",
                "applied_at", "reconciled_at"
            )
        ),
        "recentExitFacts": list(
            exits.order_by("-employment_end_date", "-created_at")[:12].values(
                "id", "fact_no", "person_id", "source_case_id", "exit_type", "employment_end_date",
                "last_working_date", "access_end_at", "status", "last_effect_error",
                "supersedes_fact_id", "change_reason", "evidence_ref", "content_hash",
                "sealed_at", "created_at"
            )
        ),
        "recentRetirements": list(
            retirements.order_by("-effective_date", "-created_at")[:12].values(
                "id", "fact_no", "person_id", "exit_fact_id", "retirement_type", "statutory_date",
                "effective_date", "pension_processing_status", "status", "created_at"
            )
        ),
        "recentRetirementPolicies": recent_retirement_policies,
        "recentRetirementPrechecks": list(
            retirement_prechecks.order_by("-created_at")[:20].values(
                "id", "person_id", "employment_relationship_id", "as_of",
                "decision", "retirement_type", "statutory_date",
                "matched_policy_id", "matched_policy_version",
                "explanation_json", "created_at",
            )
        ),
        "capabilities": {
            "exitCase": True,
            "effectSaga": True,
            "exitFact": True,
            "exitFactCorrection": True,
            "exitFactRevocation": True,
            "retirementFact": True,
            "approvalWorkflow": True,
            "handoverChecklist": True,
            "retirementPolicy": retirement_policy_available,
            "retirementPrecheck": retirement_policy_available,
            "assetProvider": _external_provider_ready("ASSET"),
            "iamProvider": _external_provider_ready("IAM"),
            "financeProvider": _external_provider_ready("FINANCE"),
            "archiveProvider": True,
        },
        "capabilityReasons": {
            "retirementPolicy": (
                None
                if retirement_policy_available
                else "渐进式延迟退休政策字段尚未完成数据库升级，当前仅可查看既有政策。"
            ),
            "retirementPrecheck": (
                None
                if retirement_policy_available
                else "退休政策升级完成前暂停预审，避免生成错误退休日期。"
            ),
        },
    }
