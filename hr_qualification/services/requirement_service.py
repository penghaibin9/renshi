"""HR09 requirement helpers backed by source-owned public evidence contracts."""

from __future__ import annotations

from datetime import date, timedelta

from hr_staff.models import HrStaffMaster


class RequirementService:
    """Legacy-friendly boolean helpers with fail-closed source authority."""

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

    def has_qualification(
        self,
        tenant_id: int,
        staff_master_id,
        category: str,
        level: str | None = None,
        as_of: date | None = None,
    ) -> bool:
        """Return True only for an ACTIVE credential proven at ``as_of``.

        ``level`` is an exact normalized catalog level code. This helper never
        guesses ordering from human labels; ranked comparisons belong to the
        typed precheck evaluator.
        """
        from hr_qualification.constants import CredentialStatus
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
