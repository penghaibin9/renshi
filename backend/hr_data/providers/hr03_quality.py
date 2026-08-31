"""Bounded built-in HR03 data-quality Provider for HR18.

Supported rule codes intentionally cover source provenance and Authority-link
completeness only. They do not encode school-specific policy thresholds. Any
unknown rule remains UNAVAILABLE so HR18 never pretends an arbitrary rule was
executed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.utils import timezone

from hr_data.services.source_gate import SourceStatus
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment


PROVIDER_VERSION = "hr03-quality-core-v1"
SUPPORTED_RULES = frozenset(
    {
        "HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
        "HR03_ASSIGNMENT_PROVENANCE_REQUIRED",
        "HR03_ASSIGNMENT_AUTHORITY_LINK_REQUIRED",
    }
)


def _fingerprint(*, rule_code: str, source_ref: str, details: dict) -> str:
    raw = json.dumps(
        {
            "ruleCode": rule_code,
            "sourceObjectRef": source_ref,
            "details": details,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _digest_header(*, tenant_id: int, rule_code: str, as_of_date: date, parameters: dict):
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "providerVersion": PROVIDER_VERSION,
                "tenantId": tenant_id,
                "ruleCode": rule_code,
                "asOfDate": as_of_date.isoformat(),
                "parameters": parameters,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    digest.update(b"\n")
    return digest


def _effective_relationships(tenant_id: int, as_of_date: date):
    return (
        HrEmploymentRelationship.objects.filter(
            tenant_id=tenant_id,
            effective_from__lte=as_of_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
        .exclude(status__in=("DRAFT", "CANCELLED"))
        .order_by("id")
    )


def _effective_assignments(tenant_id: int, as_of_date: date):
    return (
        HrStaffAssignment.objects.filter(
            tenant_id=tenant_id,
            effective_from__lte=as_of_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
        .exclude(status__in=("DRAFT", "CANCELLED"))
        .order_by("id")
    )


def _employment_provenance(*, tenant_id: int, rule_code: str, as_of_date: date, parameters: dict):
    digest = _digest_header(
        tenant_id=tenant_id,
        rule_code=rule_code,
        as_of_date=as_of_date,
        parameters=parameters,
    )
    findings = []
    rows = _effective_relationships(tenant_id, as_of_date).values_list(
        "id",
        "staff_id_id",
        "source_business_type",
        "source_business_id",
        "status",
        "effective_from",
        "effective_to",
        "version",
    )
    for row in rows.iterator(chunk_size=2000):
        digest.update(
            json.dumps(
                row,
                cls=DjangoJSONEncoder,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
        missing = []
        if not str(row[2] or "").strip():
            missing.append("sourceBusinessType")
        if not str(row[3] or "").strip():
            missing.append("sourceBusinessId")
        if missing:
            source_ref = f"employment:{row[0]}"
            details = {"missingFields": missing}
            findings.append(
                {
                    "sourceObjectRef": source_ref,
                    "fingerprint": _fingerprint(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        details=details,
                    ),
                    "details": details,
                }
            )
    return digest.hexdigest(), findings


def _assignment_provenance(*, tenant_id: int, rule_code: str, as_of_date: date, parameters: dict):
    digest = _digest_header(
        tenant_id=tenant_id,
        rule_code=rule_code,
        as_of_date=as_of_date,
        parameters=parameters,
    )
    findings = []
    rows = _effective_assignments(tenant_id, as_of_date).values_list(
        "id",
        "employment_relationship_id_id",
        "source_business_type",
        "source_business_id",
        "status",
        "effective_from",
        "effective_to",
        "version",
    )
    for row in rows.iterator(chunk_size=2000):
        digest.update(
            json.dumps(
                row,
                cls=DjangoJSONEncoder,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
        missing = []
        if not str(row[2] or "").strip():
            missing.append("sourceBusinessType")
        if not str(row[3] or "").strip():
            missing.append("sourceBusinessId")
        if missing:
            source_ref = f"assignment:{row[0]}"
            details = {"missingFields": missing}
            findings.append(
                {
                    "sourceObjectRef": source_ref,
                    "fingerprint": _fingerprint(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        details=details,
                    ),
                    "details": details,
                }
            )
    return digest.hexdigest(), findings


def _assignment_authority_links(
    *,
    tenant_id: int,
    rule_code: str,
    as_of_date: date,
    parameters: dict,
):
    allowed_keys = {"requireOrganization", "requirePosition", "requirePostCatalog"}
    if set(parameters) - allowed_keys:
        raise ValueError("unsupported HR03 assignment Authority-link parameters")
    require_organization = parameters.get("requireOrganization", True)
    require_position = parameters.get("requirePosition", True)
    require_post_catalog = parameters.get("requirePostCatalog", False)
    for value in (require_organization, require_position, require_post_catalog):
        if not isinstance(value, bool):
            raise ValueError("HR03 assignment Authority-link parameters must be boolean")
    normalized_parameters = {
        "requireOrganization": require_organization,
        "requirePosition": require_position,
        "requirePostCatalog": require_post_catalog,
    }
    digest = _digest_header(
        tenant_id=tenant_id,
        rule_code=rule_code,
        as_of_date=as_of_date,
        parameters=normalized_parameters,
    )
    findings = []
    rows = _effective_assignments(tenant_id, as_of_date).values_list(
        "id",
        "employment_relationship_id_id",
        "organization_id_id",
        "position_id_id",
        "post_catalog_id_id",
        "legacy_department_id",
        "legacy_job_position_id",
        "assignment_type",
        "status",
        "effective_from",
        "effective_to",
        "version",
    )
    for row in rows.iterator(chunk_size=2000):
        digest.update(
            json.dumps(
                row,
                cls=DjangoJSONEncoder,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")
        missing = []
        if require_organization and row[2] is None:
            missing.append("organizationId")
        if require_position and row[3] is None:
            missing.append("positionId")
        if require_post_catalog and row[4] is None:
            missing.append("postCatalogId")
        if missing:
            source_ref = f"assignment:{row[0]}"
            details = {
                "missingAuthorityLinks": missing,
                "legacyDepartmentId": row[5],
                "legacyJobPositionId": row[6],
            }
            findings.append(
                {
                    "sourceObjectRef": source_ref,
                    "fingerprint": _fingerprint(
                        rule_code=rule_code,
                        source_ref=source_ref,
                        details=details,
                    ),
                    "details": details,
                }
            )
    return digest.hexdigest(), findings


def quality_provider(
    *,
    tenant_id: int,
    source_domain: str,
    rule_code: str,
    rule_version: int,
    rule_parameters,
    as_of_date=None,
    actor_user_id=None,
):
    """Execute a bounded HR03 rule and return a typed HR18 receipt."""
    del actor_user_id, rule_version
    try:
        tenant_id = int(tenant_id)
    except (TypeError, ValueError):
        return {"status": SourceStatus.ERROR.value}
    if tenant_id <= 0 or str(source_domain or "").strip().upper() != "HR03":
        return {"status": SourceStatus.ERROR.value}
    rule_code = str(rule_code or "").strip().upper()
    if rule_code not in SUPPORTED_RULES:
        return {"status": SourceStatus.UNAVAILABLE.value}
    if rule_parameters is None:
        rule_parameters = {}
    if not isinstance(rule_parameters, dict):
        return {"status": SourceStatus.ERROR.value}
    if rule_code in {
        "HR03_EMPLOYMENT_PROVENANCE_REQUIRED",
        "HR03_ASSIGNMENT_PROVENANCE_REQUIRED",
    } and rule_parameters:
        return {"status": SourceStatus.ERROR.value}
    if as_of_date is None:
        as_of_date = timezone.localdate()
    if not isinstance(as_of_date, date):
        return {"status": SourceStatus.ERROR.value}

    try:
        if rule_code == "HR03_EMPLOYMENT_PROVENANCE_REQUIRED":
            evidence_hash, findings = _employment_provenance(
                tenant_id=tenant_id,
                rule_code=rule_code,
                as_of_date=as_of_date,
                parameters=rule_parameters,
            )
        elif rule_code == "HR03_ASSIGNMENT_PROVENANCE_REQUIRED":
            evidence_hash, findings = _assignment_provenance(
                tenant_id=tenant_id,
                rule_code=rule_code,
                as_of_date=as_of_date,
                parameters=rule_parameters,
            )
        else:
            evidence_hash, findings = _assignment_authority_links(
                tenant_id=tenant_id,
                rule_code=rule_code,
                as_of_date=as_of_date,
                parameters=rule_parameters,
            )
    except Exception:
        return {"status": SourceStatus.ERROR.value}

    return {
        "status": SourceStatus.OK.value,
        "providerVersion": PROVIDER_VERSION,
        "evidenceHash": evidence_hash,
        "findings": findings,
    }
