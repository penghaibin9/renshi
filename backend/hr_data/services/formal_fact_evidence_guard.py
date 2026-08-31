"""Revalidate frozen HR13/HR14 evidence before returning a historical value."""

from __future__ import annotations

from hr_data.providers.formal_facts import hr13_asof_provider, hr14_asof_provider
from hr_data.services.evaluation_service import AsOfEvaluationError, AsOfEvaluationResult


_PROVIDERS = {
    "HR13": hr13_asof_provider,
    "HR14": hr14_asof_provider,
}


def verify_formal_fact_evidence(
    *,
    tenant_id: int,
    domain: str,
    result: AsOfEvaluationResult,
    actor_user_id=None,
) -> None:
    domain = str(domain or "").strip().upper()
    provider = _PROVIDERS.get(domain)
    if provider is None:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
            "formal-fact evidence guard supports HR13 or HR14 only",
        )
    frozen_hash = str(
        (getattr(result.evidence, "provider_evidence_hashes_json", {}) or {}).get(domain)
        or ""
    ).strip().lower()
    if not frozen_hash:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_EVIDENCE_STALE",
            f"frozen evidence does not contain a {domain} provider hash",
        )
    receipt = provider(
        tenant_id=int(tenant_id),
        source_domain=domain,
        definition_kind=result.definition_kind,
        definition_code=result.definition_code,
        definition_version=result.definition_version,
        as_of_date=result.as_of_date,
        actor_user_id=actor_user_id,
    )
    current_hash = str((receipt or {}).get("evidenceHash") or "").strip().lower()
    if (receipt or {}).get("status") != "OK" or not current_hash or current_hash != frozen_hash:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_EVIDENCE_STALE",
            f"authoritative {domain} facts changed after frozen evidence creation; use a new evidenceNo",
        )
