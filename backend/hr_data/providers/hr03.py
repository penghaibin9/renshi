"""HR03 effective-dated historical evidence Provider for HR18.

This adapter consumes only HR03 authority facts that are explicitly historical:
HrEmploymentRelationship and HrStaffAssignment.  It never falls back to
HrStaffMaster current projections or legacy Employee current-state tables.
Unsupported HR03 field paths fail closed with UNAVAILABLE so HR18 cannot label a
formal historical cut COMPLETE from current-state data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Iterable

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q

from hr_data.models import (
    AsOfEvidenceSnapshot,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
)
from hr_data.services.source_gate import SourceStatus
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment


PROVIDER_VERSION = "hr03-effective-dated-v1"

_HR03_NAMESPACES = frozenset(
    {
        "employment",
        "relationship",
        "assignment",
        "status",
        "staff",
        "person",
        "identity",
        "contact",
        "education",
        "credential",
        "material",
    }
)

_EMPLOYMENT_FIELDS = frozenset(
    {
        "employment.staffid",
        "employment.status",
        "employment.relationshiptype",
        "employment.employmenttype",
        "employment.effectivefrom",
        "employment.effectiveto",
        "employment.reasoncode",
        "relationship.staffid",
        "relationship.status",
        "relationship.relationshiptype",
        "relationship.employmenttype",
        "relationship.effectivefrom",
        "relationship.effectiveto",
        "relationship.reasoncode",
    }
)

_ASSIGNMENT_FIELDS = frozenset(
    {
        "assignment.organizationid",
        "assignment.positionid",
        "assignment.postcatalogid",
        "assignment.assignmenttype",
        "assignment.rolecode",
        "assignment.fte",
        "assignment.effectivefrom",
        "assignment.effectiveto",
        "assignment.status",
        "assignment.reportingstaffid",
    }
)

_SUPPORTED_FIELDS = _EMPLOYMENT_FIELDS | _ASSIGNMENT_FIELDS


def _normalize_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


def _predicate_fields(node) -> set[str]:
    fields: set[str] = set()
    if not isinstance(node, dict):
        return fields
    if "field" in node:
        field = str(node.get("field") or "").strip()
        if field:
            fields.add(field)
        return fields
    for key in ("and", "or"):
        children = node.get(key)
        if isinstance(children, list):
            for child in children:
                fields.update(_predicate_fields(child))
    if "not" in node:
        fields.update(_predicate_fields(node.get("not")))
    return fields


def _definition(
    *,
    tenant_id: int,
    definition_kind: str,
    definition_code: str,
    definition_version: int,
):
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.POPULATION:
        return PopulationDefinitionVersion.objects.filter(
            tenant_id=tenant_id,
            population_code=definition_code,
            version_no=definition_version,
        ).first()
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        return DimensionDefinitionVersion.objects.filter(
            tenant_id=tenant_id,
            dimension_code=definition_code,
            version_no=definition_version,
        ).first()
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.METRIC:
        return MetricDefinitionVersion.objects.filter(
            tenant_id=tenant_id,
            metric_code=definition_code,
            version_no=definition_version,
        ).first()
    return None


def _population_for_metric(*, tenant_id: int, metric: MetricDefinitionVersion):
    try:
        expression = json.loads(metric.expression or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    try:
        population_version = int(expression.get("populationVersion"))
    except (TypeError, ValueError):
        return None
    return PopulationDefinitionVersion.objects.filter(
        tenant_id=tenant_id,
        population_code=metric.population_code,
        version_no=population_version,
    ).first()


def _required_fields(*, tenant_id: int, definition_kind: str, definition) -> tuple[set[str], bool]:
    """Return definition fields plus whether HR03 is the population root authority."""
    fields: set[str] = set()
    root_is_hr03 = False

    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.POPULATION:
        root_is_hr03 = str(definition.root_domain or "").upper() == "HR03"
        fields.update(_predicate_fields(definition.predicate_json))
    elif definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        fields.add(str(definition.attribute_path or ""))
    elif definition_kind == AsOfEvidenceSnapshot.DefinitionKind.METRIC:
        population = _population_for_metric(tenant_id=tenant_id, metric=definition)
        if population is None:
            return {"__invalid_population__"}, False
        root_is_hr03 = str(population.root_domain or "").upper() == "HR03"
        fields.update(_predicate_fields(population.predicate_json))
        try:
            expression = json.loads(definition.expression or "{}")
        except (TypeError, json.JSONDecodeError):
            return {"__invalid_expression__"}, root_is_hr03
        metric_field = str(expression.get("field") or "").strip()
        if metric_field:
            fields.add(metric_field)
    return fields, root_is_hr03


def _fact_kinds(fields: Iterable[str], *, root_is_hr03: bool, hr03_only: bool):
    normalized = {_normalize_path(field) for field in fields if str(field or "").strip()}
    kinds: set[str] = set()
    unsupported: set[str] = set()

    for field in normalized:
        namespace = field.split(".", 1)[0]
        if namespace in _HR03_NAMESPACES:
            if field not in _SUPPORTED_FIELDS:
                unsupported.add(field)
                continue
            if field in _EMPLOYMENT_FIELDS:
                kinds.add("employment")
            if field in _ASSIGNMENT_FIELDS:
                kinds.add("assignment")
        elif hr03_only:
            unsupported.add(field)

    if root_is_hr03 and not normalized:
        unsupported.add("hr03-root-without-supported-field-contract")
    if root_is_hr03 and not kinds and not unsupported:
        unsupported.add("hr03-root-without-effective-dated-field")
    return kinds, unsupported


def _active_relationship_rows(tenant_id: int, as_of_date: date):
    return (
        HrEmploymentRelationship.objects.filter(
            tenant_id=tenant_id,
            effective_from__lte=as_of_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
        .exclude(status__in=("DRAFT", "CANCELLED"))
        .order_by("id")
        .values_list(
            "id",
            "staff_id_id",
            "relationship_type",
            "employment_type",
            "effective_from",
            "effective_to",
            "status",
            "source_business_type",
            "source_business_id",
            "reason_code",
            "version",
        )
        .iterator(chunk_size=2000)
    )


def _active_assignment_rows(tenant_id: int, as_of_date: date):
    return (
        HrStaffAssignment.objects.filter(
            tenant_id=tenant_id,
            effective_from__lte=as_of_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
        .exclude(status__in=("DRAFT", "CANCELLED"))
        .order_by("id")
        .values_list(
            "id",
            "employment_relationship_id_id",
            "organization_id_id",
            "position_id_id",
            "post_catalog_id_id",
            "legacy_department_id",
            "legacy_job_position_id",
            "assignment_type",
            "assignment_role_code",
            "fte",
            "effective_from",
            "effective_to",
            "reporting_staff_id_id",
            "status",
            "source_business_type",
            "source_business_id",
            "version",
        )
        .iterator(chunk_size=2000)
    )


def _evidence_hash(*, tenant_id: int, as_of_date: date, fact_kinds: set[str]) -> str:
    digest = hashlib.sha256()
    header = {
        "providerVersion": PROVIDER_VERSION,
        "tenantId": tenant_id,
        "asOfDate": as_of_date.isoformat(),
        "factKinds": sorted(fact_kinds),
    }
    digest.update(
        json.dumps(
            header,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    digest.update(b"\n")

    readers = []
    if "employment" in fact_kinds:
        readers.append(("employment", _active_relationship_rows(tenant_id, as_of_date)))
    if "assignment" in fact_kinds:
        readers.append(("assignment", _active_assignment_rows(tenant_id, as_of_date)))
    for kind, rows in readers:
        for row in rows:
            digest.update(kind.encode("ascii"))
            digest.update(b":")
            digest.update(
                json.dumps(
                    row,
                    cls=DjangoJSONEncoder,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()


def asof_provider(
    *,
    tenant_id: int,
    source_domain: str,
    definition_kind: str,
    definition_code: str,
    definition_version: int,
    as_of_date: date,
    actor_user_id=None,
):
    """Return a typed HR18 source receipt for HR03 effective-dated facts."""
    del actor_user_id
    if int(tenant_id or 0) <= 0 or str(source_domain or "").upper() != "HR03":
        return {"status": SourceStatus.ERROR.value}
    if not isinstance(as_of_date, date):
        return {"status": SourceStatus.ERROR.value}

    definition = _definition(
        tenant_id=int(tenant_id),
        definition_kind=str(definition_kind or "").upper(),
        definition_code=str(definition_code or "").upper(),
        definition_version=int(definition_version),
    )
    if definition is None:
        return {"status": SourceStatus.ERROR.value}

    fields, root_is_hr03 = _required_fields(
        tenant_id=int(tenant_id),
        definition_kind=str(definition_kind or "").upper(),
        definition=definition,
    )
    if "__invalid_population__" in fields or "__invalid_expression__" in fields:
        return {"status": SourceStatus.ERROR.value}

    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        hr03_only = True
    else:
        domains = {str(item or "").upper() for item in (definition.source_domains or [])}
        hr03_only = domains == {"HR03"}

    fact_kinds, unsupported = _fact_kinds(
        fields,
        root_is_hr03=root_is_hr03,
        hr03_only=hr03_only,
    )
    if unsupported:
        return {
            "status": SourceStatus.UNAVAILABLE.value,
            "sourceVersion": PROVIDER_VERSION,
            "evidenceHash": "",
        }
    if not fact_kinds:
        return {
            "status": SourceStatus.UNAVAILABLE.value,
            "sourceVersion": PROVIDER_VERSION,
            "evidenceHash": "",
        }

    return {
        "status": SourceStatus.OK.value,
        "sourceVersion": PROVIDER_VERSION,
        "evidenceHash": _evidence_hash(
            tenant_id=int(tenant_id),
            as_of_date=as_of_date,
            fact_kinds=fact_kinds,
        ),
    }
