"""HR09 credential provider used by the double-teacher evidence aggregator."""

from __future__ import annotations

import uuid
from datetime import date

from hr_qualification.constants import CredentialStatus, ProviderStatus, VerificationResult
from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderError,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)

PROVIDER_VERSION = "hr09-credential-evidence-v1"


class Hr09CredentialProvider(HrEvidenceProvider):
    provider_key = "HR09_CREDENTIAL"
    owner_domain = "hr_qualification"
    timeout_seconds = 5
    sensitivity = "RESTRICTED_HR"

    def provide(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
        source_version: str | None = None,
    ) -> ProviderEvidenceResult:
        from hr_qualification.public import (
            CredentialEvidenceUnavailable,
            get_formal_credential_evidence_for_person,
        )

        try:
            evidence = get_formal_credential_evidence_for_person(
                tenant_id=tenant_id,
                person_id=person_id,
                staff_id=staff_master_id,
                as_of=as_of,
                source_version=source_version or "v1",
            )
        except CredentialEvidenceUnavailable as exc:
            return ProviderEvidenceResult.unavailable(
                reason_code=exc.code,
                message=str(exc),
                provider_version=PROVIDER_VERSION,
            )

        items = []
        for credential in evidence.rows:
            if credential.status == CredentialStatus.ACTIVE:
                verification_status = (
                    credential.current_verification_status or VerificationResult.VERIFIED
                )
            else:
                # A historically verified credential that is expired at as_of is
                # still an auditable fact, but it cannot satisfy a verified-active
                # credential requirement.
                verification_status = credential.status
            items.append(
                ProviderEvidenceItem(
                    source_domain="HR09_CREDENTIAL",
                    source_object_type="HrPersonCredential",
                    source_object_id=str(credential.credential_id),
                    evidence_date=credential.valid_from or credential.as_of,
                    title=credential.credential_name,
                    role=credential.category,
                    quantitative_value=(
                        float(credential.level_rank)
                        if credential.level_rank is not None
                        else None
                    ),
                    verification_status=verification_status,
                    document_refs=list(credential.document_refs),
                    snapshot_json=credential.snapshot(),
                )
            )

        source_updated_at = max(
            (
                credential.last_verified_at
                for credential in evidence.rows
                if credential.last_verified_at is not None
            ),
            default=None,
        )
        if evidence.uncertain_staff_ids:
            return ProviderEvidenceResult(
                status=ProviderStatus.PARTIAL,
                items=items,
                errors=[
                    ProviderError(
                        code="CREDENTIAL_HISTORY_UNAVAILABLE",
                        message=(
                            "historical HR09 credential state cannot be proven for staff: "
                            + ",".join(
                                str(value) for value in evidence.uncertain_staff_ids
                            )
                        ),
                    )
                ],
                source_updated_at=source_updated_at,
                provider_version=PROVIDER_VERSION,
            )
        return ProviderEvidenceResult.ok(
            items=items,
            source_updated_at=source_updated_at,
            provider_version=PROVIDER_VERSION,
        )
