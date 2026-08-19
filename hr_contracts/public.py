"""Source-owned HR07 formal agreement evidence for cross-domain consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q

from hr_contracts.models import HrContractVersion

PROVIDER_VERSION = "hr07-agreement-evidence-v1"
FORMAL_VERSION_STATUSES = frozenset(
    {
        HrContractVersion.Status.EFFECTIVE,
        HrContractVersion.Status.SUPERSEDED,
        HrContractVersion.Status.TERMINATED,
        HrContractVersion.Status.EXPIRED,
    }
)


class AgreementEvidenceUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AgreementEvidenceRow:
    agreement_id: Any
    version_id: Any
    staff_id: Any
    employment_relationship_id: Any
    agreement_no: str
    agreement_type: str
    agreement_title: str
    version_no: int
    effective_from: date
    effective_to: date | None
    version_status: str
    content_hash: str

    def snapshot(self) -> dict:
        return {
            "agreement_id": str(self.agreement_id),
            "version_id": str(self.version_id),
            "staff_id": str(self.staff_id),
            "employment_relationship_id": str(self.employment_relationship_id),
            "agreement_no": self.agreement_no,
            "agreement_type": self.agreement_type,
            "agreement_title": self.agreement_title,
            "version_no": self.version_no,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "status": self.version_status,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class AgreementEvidence:
    rows: tuple[AgreementEvidenceRow, ...]
    missing_staff_ids: tuple[Any, ...]
    source_version: str = PROVIDER_VERSION


def get_formal_agreement_evidence(
    *,
    tenant_id: int,
    staff_ids: list,
    as_of: date,
    source_version: str | None = None,
) -> AgreementEvidence:
    if not tenant_id:
        raise AgreementEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise AgreementEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version not in (None, "", "v1", PROVIDER_VERSION):
        raise AgreementEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR07 source version: {source_version}",
        )
    if not staff_ids:
        return AgreementEvidence((), ())

    requested = tuple(dict.fromkeys(staff_ids))
    versions = list(
        HrContractVersion.objects.filter(
            tenant_id=tenant_id,
            agreement__tenant_id=tenant_id,
            agreement__staff_id__in=requested,
            status__in=FORMAL_VERSION_STATUSES,
            effective_from__lte=as_of,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
        .select_related("agreement")
        .order_by("agreement__staff_id", "agreement_id", "-version_no")
    )

    seen_agreements = set()
    present_staff = set()
    rows = []
    for version in versions:
        agreement_key = version.agreement_id
        if agreement_key in seen_agreements:
            raise AgreementEvidenceUnavailable(
                "FORMAL_VERSION_CONFLICT",
                f"multiple formal HR07 versions cover as_of for agreement {agreement_key}",
            )
        seen_agreements.add(agreement_key)
        agreement = version.agreement
        present_staff.add(agreement.staff_id)
        rows.append(
            AgreementEvidenceRow(
                agreement_id=agreement.id,
                version_id=version.id,
                staff_id=agreement.staff_id,
                employment_relationship_id=agreement.employment_relationship_id,
                agreement_no=agreement.agreement_no,
                agreement_type=agreement.agreement_type,
                agreement_title=agreement.agreement_title,
                version_no=version.version_no,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                version_status=version.status,
                content_hash=version.content_hash,
            )
        )

    missing = tuple(sorted((value for value in requested if value not in present_staff), key=str))
    return AgreementEvidence(rows=tuple(rows), missing_staff_ids=missing)
