"""HR09 requirement helpers backed by source-owned public evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from hr_qualification.constants import (
    CredentialStatus,
    RequirementMatchResult,
    VerificationResult,
)
from hr_qualification.models import HrCredentialRequirement, HrPersonCredential
from hr_staff.models import HrStaffMaster


@dataclass(frozen=True)
class RequirementMatchItem:
    requirement: HrCredentialRequirement
    result: RequirementMatchResult
    matched_credential_id: str | None = None
    detail: str = ""


def _level_rank(catalog, level_code: str) -> int | None:
    if not level_code:
        return None
    schema = catalog.level_schema or {}
    levels = schema.get("levels", []) if isinstance(schema, dict) else []
    for level in levels:
        if not isinstance(level, dict) or str(level.get("code", "")) != str(level_code):
            continue
        try:
            return int(level.get("rank"))
        except (TypeError, ValueError):
            return None
    return None


class RequirementService:
    """Qualification requirement matching with fail-closed source authority."""

    def __init__(self, providers=None):
        self.providers = providers or {}

    @staticmethod
    def _canonical_identity(tenant_id: int, staff_master_id):
        return (
            HrStaffMaster.objects.filter(
                tenant_id=tenant_id,
                id=staff_master_id,
            )
            .only("id", "person_id")
            .first()
        )

    @staticmethod
    def compare_person_to_requirement(
        credential: HrPersonCredential,
        requirement: HrCredentialRequirement,
        as_of: date | None = None,
    ) -> RequirementMatchItem:
        """Compare one credential against one requirement without guessing truth.

        The credential API still exposes this legacy-friendly single-record
        comparison, but the decision rules follow the current HR09 authority:
        tenant/catalog/category must match, only ACTIVE facts can satisfy a
        requirement, verification is explicit when required, validity uses the
        repository-wide half-open interval convention, and minimum-level ordering
        is accepted only when the catalog schema actually proves both ranks.
        """
        as_of = as_of or date.today()
        matched_id = str(credential.id)

        if credential.tenant_id != requirement.tenant_id:
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.NOT_APPLICABLE,
                detail="Credential and requirement belong to different tenants",
            )

        catalog = credential.catalog_item_id
        if (
            requirement.credential_category
            and requirement.credential_category != catalog.category
        ):
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.NOT_APPLICABLE,
                detail=(
                    f"Credential category {catalog.category} "
                    f"does not match requirement {requirement.credential_category}"
                ),
            )

        if (
            requirement.catalog_item_id_id is not None
            and requirement.catalog_item_id_id != credential.catalog_item_id_id
        ):
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.NOT_APPLICABLE,
                detail="Credential catalog item does not match the exact requirement",
            )

        if credential.status == CredentialStatus.EXPIRED:
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.EXPIRED,
                matched_credential_id=matched_id,
                detail="Credential is expired",
            )
        if credential.status != CredentialStatus.ACTIVE:
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.MISSING,
                matched_credential_id=matched_id,
                detail=f"Credential status {credential.status} is not ACTIVE",
            )

        if requirement.valid_on_date_required:
            if credential.valid_from is not None and credential.valid_from > as_of:
                return RequirementMatchItem(
                    requirement=requirement,
                    result=RequirementMatchResult.MISSING,
                    matched_credential_id=matched_id,
                    detail=f"Credential is not valid until {credential.valid_from}",
                )
            if credential.valid_to is not None and credential.valid_to <= as_of:
                return RequirementMatchItem(
                    requirement=requirement,
                    result=RequirementMatchResult.EXPIRED,
                    matched_credential_id=matched_id,
                    detail=f"Credential validity ended on {credential.valid_to}",
                )

        if (
            requirement.verification_required
            and credential.current_verification_status != VerificationResult.VERIFIED
        ):
            return RequirementMatchItem(
                requirement=requirement,
                result=RequirementMatchResult.UNVERIFIED,
                matched_credential_id=matched_id,
                detail=(
                    "Verification required but status is "
                    f"{credential.current_verification_status or '<empty>'}"
                ),
            )

        if requirement.minimum_level:
            if credential.level_code != requirement.minimum_level:
                actual_rank = _level_rank(catalog, credential.level_code)
                minimum_rank = _level_rank(catalog, requirement.minimum_level)
                if (
                    actual_rank is None
                    or minimum_rank is None
                    or actual_rank < minimum_rank
                ):
                    return RequirementMatchItem(
                        requirement=requirement,
                        result=RequirementMatchResult.LOWER_LEVEL,
                        matched_credential_id=matched_id,
                        detail=(
                            "Credential level does not prove the required minimum: "
                            f"actual={credential.level_code or '<empty>'}, "
                            f"minimum={requirement.minimum_level}"
                        ),
                    )

        return RequirementMatchItem(
            requirement=requirement,
            result=RequirementMatchResult.MET,
            matched_credential_id=matched_id,
            detail="OK",
        )

    def has_qualification(
        self,
        tenant_id: int,
        staff_master_id,
        category: str,
        level: str | None = None,
        as_of: date | None = None,
    ) -> bool:
        """Return True only for a VERIFIED + ACTIVE credential proven at ``as_of``.

        ``level`` is an exact normalized catalog level code. This helper never
        guesses ordering from human labels; ranked comparisons belong to the
        typed precheck evaluator.
        """
        from hr_qualification.public import (
            CredentialEvidenceUnavailable,
            get_formal_credential_evidence_for_person,
        )

        as_of = as_of or date.today()
        identity = self._canonical_identity(tenant_id, staff_master_id)
        if identity is None:
            return False
        try:
            evidence = get_formal_credential_evidence_for_person(
                tenant_id=tenant_id,
                person_id=identity.person_id_id,
                staff_id=identity.id,
                as_of=as_of,
            )
        except CredentialEvidenceUnavailable:
            return False
        if evidence.uncertain_staff_ids:
            return False
        for credential in evidence.rows:
            if credential.status != CredentialStatus.ACTIVE:
                continue
            if credential.current_verification_status != VerificationResult.VERIFIED:
                continue
            if credential.category != category:
                continue
            if level is not None and credential.level_code != level:
                continue
            return True
        return False

    def has_min_experience_days(
        self,
        tenant_id: int,
        staff_master_id,
        experience_type: str,
        min_days: int,
        as_of: date | None = None,
    ) -> bool:
        """Count verified HR03 work coverage without double-counting overlaps."""
        from hr_staff.public import (
            BackgroundEvidenceUnavailable,
            get_verified_background_evidence,
        )

        as_of = as_of or date.today()
        identity = self._canonical_identity(tenant_id, staff_master_id)
        if identity is None:
            return False
        try:
            evidence = get_verified_background_evidence(
                tenant_id=tenant_id,
                person_id=identity.person_id_id,
                staff_id=identity.id,
                as_of=as_of,
            )
        except BackgroundEvidenceUnavailable:
            return False

        intervals = []
        for row in evidence.rows:
            if row.kind != "WORK":
                continue
            snapshot = row.snapshot or {}
            if snapshot.get("experienceType") != experience_type:
                continue
            raw_start = snapshot.get("startDate")
            if not raw_start:
                continue
            try:
                start = date.fromisoformat(str(raw_start))
            except ValueError:
                continue
            raw_end = snapshot.get("endDate")
            try:
                end = date.fromisoformat(str(raw_end)) if raw_end else as_of
            except ValueError:
                continue
            end = min(end, as_of)
            if end <= start:
                continue
            intervals.append((start, end))

        if not intervals:
            return min_days <= 0
        intervals.sort()
        merged = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
                continue
            if end > merged[-1][1]:
                merged[-1][1] = end
        total_days = sum((end - start).days for start, end in merged)
        return total_days >= int(min_days)

    def provider_available(self, provider_key: str) -> bool:
        return provider_key in self.providers
