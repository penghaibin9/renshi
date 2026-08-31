"""Source-owned HR02 organization evidence contract for cross-domain consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q

from hr_structure.models import HrOrganizationVersion
from hr_structure.selectors.effective import FORMAL_STATUSES

PROVIDER_VERSION = "hr02-organization-evidence-v1"


class OrganizationEvidenceUnavailable(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class OrganizationEvidenceRow:
    organization_id: Any
    stable_code: str
    name: str
    short_name: str
    org_type: str
    identity_status: str
    validity_from: date
    validity_to: date | None
    version_no: int

    def snapshot(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "stable_code": self.stable_code,
            "name": self.name,
            "short_name": self.short_name,
            "org_type": self.org_type,
            "identity_status": self.identity_status,
            "validity_from": self.validity_from.isoformat(),
            "validity_to": self.validity_to.isoformat() if self.validity_to else None,
            "version_no": self.version_no,
        }


@dataclass(frozen=True)
class OrganizationEvidence:
    rows: tuple[OrganizationEvidenceRow, ...]
    missing_organization_ids: tuple[Any, ...]
    source_version: str = PROVIDER_VERSION


def _dedupe_ids(values: list) -> tuple[Any, ...]:
    result = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def get_organization_evidence(
    *,
    tenant_id: int,
    organization_ids: list,
    as_of: date,
    source_version: str | None = None,
) -> OrganizationEvidence:
    if not tenant_id:
        raise OrganizationEvidenceUnavailable(
            "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
        )
    if not isinstance(as_of, date):
        raise OrganizationEvidenceUnavailable(
            "AS_OF_REQUIRED", "as_of must be a date"
        )
    if source_version not in (None, "", "v1", PROVIDER_VERSION):
        raise OrganizationEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported HR02 source version: {source_version}",
        )
    if not organization_ids:
        return OrganizationEvidence((), ())

    requested = _dedupe_ids(organization_ids)
    versions = list(
        HrOrganizationVersion.objects.filter(
            tenant_id=tenant_id,
            organization_id_id__in=requested,
            status__in=FORMAL_STATUSES,
            validity_from__lte=as_of,
        )
        .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=as_of))
        .select_related("organization_id")
        .order_by("organization_id_id", "-version_no")
    )

    chosen = {}
    for version in versions:
        organization_id = version.organization_id_id
        key = str(organization_id)
        if key in chosen:
            raise OrganizationEvidenceUnavailable(
                "FORMAL_VERSION_CONFLICT",
                f"multiple formal HR02 organization versions cover as_of for {organization_id}",
            )
        chosen[key] = version

    missing = tuple(
        sorted((value for value in requested if str(value) not in chosen), key=str)
    )
    rows = tuple(
        OrganizationEvidenceRow(
            organization_id=version.organization_id_id,
            stable_code=version.organization_id.stable_code,
            name=version.name,
            short_name=version.short_name,
            org_type=version.org_type,
            identity_status=version.organization_id.identity_status,
            validity_from=version.validity_from,
            validity_to=version.validity_to,
            version_no=version.version_no,
        )
        for version in chosen.values()
    )
    return OrganizationEvidence(rows=rows, missing_organization_ids=missing)
