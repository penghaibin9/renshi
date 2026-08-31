"""Fail-closed as-of adapters for parallel formal-fact HR authorities.

These adapters intentionally avoid import-time dependencies on HR13/HR14/HR16.
Before the parallel authority app is merged, Django's app registry lookup fails
and the source remains UNAVAILABLE.  After integration, the same adapter hashes
only append-only/effective formal facts.  Mutable workflow/current-projection
fields are not accepted as historical evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from hr_data.models import (
    AsOfEvidenceSnapshot,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
)
from hr_data.services.source_gate import SourceStatus


@dataclass(frozen=True)
class FactSpec:
    key: str
    app_label: str
    model_name: str
    as_of_field: str
    allowed_statuses: tuple[str, ...]
    hash_fields: tuple[str, ...]


@dataclass(frozen=True)
class DomainSpec:
    domain: str
    provider_version: str
    namespaces: frozenset[str]
    field_fact_map: dict[str, str]
    facts: dict[str, FactSpec]


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
        population_version = int(expression.get("populationVersion"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return PopulationDefinitionVersion.objects.filter(
        tenant_id=tenant_id,
        population_code=metric.population_code,
        version_no=population_version,
    ).first()


def _required_fields(*, tenant_id: int, definition_kind: str, definition):
    fields: set[str] = set()
    root_domain = ""
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.POPULATION:
        root_domain = str(definition.root_domain or "").upper()
        fields.update(_predicate_fields(definition.predicate_json))
    elif definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        fields.add(str(definition.attribute_path or ""))
        root_domain = str(definition.source_domain or "").upper()
    elif definition_kind == AsOfEvidenceSnapshot.DefinitionKind.METRIC:
        population = _population_for_metric(tenant_id=tenant_id, metric=definition)
        if population is None:
            return {"__invalid_population__"}, ""
        root_domain = str(population.root_domain or "").upper()
        fields.update(_predicate_fields(population.predicate_json))
        try:
            expression = json.loads(definition.expression or "{}")
        except (TypeError, json.JSONDecodeError):
            return {"__invalid_expression__"}, root_domain
        metric_field = str(expression.get("field") or "").strip()
        if metric_field:
            fields.add(metric_field)
    return fields, root_domain


def _source_domains(definition_kind: str, definition) -> set[str]:
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        return {str(definition.source_domain or "").upper()}
    return {str(item or "").upper() for item in (definition.source_domains or [])}


def _fact_keys(
    *,
    spec: DomainSpec,
    fields: Iterable[str],
    root_domain: str,
    only_source: bool,
):
    normalized = {_normalize_path(field) for field in fields if str(field or "").strip()}
    fact_keys: set[str] = set()
    unsupported: set[str] = set()
    for field in normalized:
        namespace = field.split(".", 1)[0]
        if namespace in spec.namespaces:
            fact_key = spec.field_fact_map.get(field)
            if fact_key is None:
                unsupported.add(field)
            else:
                fact_keys.add(fact_key)
        elif only_source:
            unsupported.add(field)
    if root_domain == spec.domain and not fact_keys and not unsupported:
        unsupported.add(f"{spec.domain.lower()}-root-without-formal-fact-field")
    return fact_keys, unsupported


def _model(spec: FactSpec):
    try:
        return apps.get_model(spec.app_label, spec.model_name)
    except LookupError:
        return None


def _hash_facts(
    *,
    tenant_id: int,
    as_of_date: date,
    domain_spec: DomainSpec,
    fact_keys: set[str],
):
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "providerVersion": domain_spec.provider_version,
                "tenantId": tenant_id,
                "asOfDate": as_of_date.isoformat(),
                "factKinds": sorted(fact_keys),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")

    for key in sorted(fact_keys):
        fact_spec = domain_spec.facts[key]
        model = _model(fact_spec)
        if model is None:
            return None
        queryset = model.objects.filter(
            tenant_id=tenant_id,
            **{f"{fact_spec.as_of_field}__lte": as_of_date},
        )
        if fact_spec.allowed_statuses:
            queryset = queryset.filter(status__in=fact_spec.allowed_statuses)
        rows = (
            queryset.order_by("id")
            .values_list(*fact_spec.hash_fields)
            .iterator(chunk_size=2000)
        )
        for row in rows:
            digest.update(key.encode("ascii"))
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


def _provider(
    *,
    spec: DomainSpec,
    tenant_id: int,
    source_domain: str,
    definition_kind: str,
    definition_code: str,
    definition_version: int,
    as_of_date: date,
):
    if int(tenant_id or 0) <= 0 or str(source_domain or "").upper() != spec.domain:
        return {"status": SourceStatus.ERROR.value}
    if not isinstance(as_of_date, date):
        return {"status": SourceStatus.ERROR.value}
    definition_kind = str(definition_kind or "").upper()
    try:
        definition_version = int(definition_version)
    except (TypeError, ValueError):
        return {"status": SourceStatus.ERROR.value}
    definition = _definition(
        tenant_id=int(tenant_id),
        definition_kind=definition_kind,
        definition_code=str(definition_code or "").upper(),
        definition_version=definition_version,
    )
    if definition is None:
        return {"status": SourceStatus.ERROR.value}
    fields, root_domain = _required_fields(
        tenant_id=int(tenant_id),
        definition_kind=definition_kind,
        definition=definition,
    )
    if "__invalid_population__" in fields or "__invalid_expression__" in fields:
        return {"status": SourceStatus.ERROR.value}
    domains = _source_domains(definition_kind, definition)
    fact_keys, unsupported = _fact_keys(
        spec=spec,
        fields=fields,
        root_domain=root_domain,
        only_source=domains == {spec.domain},
    )
    if unsupported or not fact_keys:
        return {
            "status": SourceStatus.UNAVAILABLE.value,
            "sourceVersion": spec.provider_version,
            "evidenceHash": "",
        }
    evidence_hash = _hash_facts(
        tenant_id=int(tenant_id),
        as_of_date=as_of_date,
        domain_spec=spec,
        fact_keys=fact_keys,
    )
    if evidence_hash is None:
        return {
            "status": SourceStatus.UNAVAILABLE.value,
            "sourceVersion": spec.provider_version,
            "evidenceHash": "",
        }
    return {
        "status": SourceStatus.OK.value,
        "sourceVersion": spec.provider_version,
        "evidenceHash": evidence_hash,
    }


HR13_SPEC = DomainSpec(
    domain="HR13",
    provider_version="hr13-title-facts-v1",
    namespaces=frozenset({"title", "professionaltitle"}),
    field_fact_map={
        _normalize_path(field): "title"
        for field in (
            "title.personId",
            "title.titleCode",
            "title.titleName",
            "title.titleSeriesCode",
            "title.titleLevelCode",
            "title.effectiveFrom",
            "title.effectiveTo",
            "title.status",
            "professionalTitle.personId",
            "professionalTitle.titleCode",
            "professionalTitle.titleName",
            "professionalTitle.titleSeriesCode",
            "professionalTitle.titleLevelCode",
            "professionalTitle.effectiveFrom",
            "professionalTitle.effectiveTo",
            "professionalTitle.status",
        )
    },
    facts={
        "title": FactSpec(
            key="title",
            app_label="hr_title",
            model_name="ProfessionalTitleResult",
            as_of_field="effective_from",
            allowed_statuses=("EFFECTIVE", "REVISED", "REVOKED"),
            hash_fields=(
                "id",
                "result_no",
                "person_id",
                "application_case_id",
                "title_code",
                "title_name",
                "title_series_code",
                "title_level_code",
                "effective_from",
                "effective_to",
                "status",
                "supersedes_result_id",
            ),
        )
    },
)


HR14_SPEC = DomainSpec(
    domain="HR14",
    provider_version="hr14-appointment-facts-v1",
    namespaces=frozenset({"appointment"}),
    field_fact_map={
        _normalize_path(field): "appointment"
        for field in (
            "appointment.personId",
            "appointment.positionInstanceId",
            "appointment.levelCode",
            "appointment.effectiveFrom",
            "appointment.effectiveTo",
            "appointment.status",
        )
    },
    facts={
        "appointment": FactSpec(
            key="appointment",
            app_label="hr_appointment",
            model_name="PositionAppointmentFact",
            as_of_field="effective_from",
            allowed_statuses=("EFFECTIVE", "REVISED", "ENDED", "REVOKED"),
            hash_fields=(
                "id",
                "appointment_no",
                "person_id",
                "position_instance_id",
                "application_case_id",
                "level_code",
                "effective_from",
                "effective_to",
                "status",
                "supersedes_fact_id",
            ),
        )
    },
)


HR16_SPEC = DomainSpec(
    domain="HR16",
    provider_version="hr16-exit-retirement-facts-v1",
    namespaces=frozenset({"exit", "retirement"}),
    field_fact_map={
        **{
            _normalize_path(field): "exit"
            for field in (
                "exit.personId",
                "exit.employmentRelationshipId",
                "exit.exitType",
                "exit.employmentEndDate",
                "exit.lastWorkingDate",
                "exit.accessEndAt",
            )
        },
        **{
            _normalize_path(field): "retirement"
            for field in (
                "retirement.personId",
                "retirement.retirementType",
                "retirement.statutoryDate",
                "retirement.effectiveDate",
            )
        },
    },
    facts={
        "exit": FactSpec(
            key="exit",
            app_label="hr_exit",
            model_name="ExitFact",
            as_of_field="employment_end_date",
            allowed_statuses=("EFFECTIVE", "REVISED", "REVOKED"),
            hash_fields=(
                "id",
                "fact_no",
                "person_id",
                "employment_relationship_id",
                "source_case_id",
                "exit_type",
                "employment_end_date",
                "last_working_date",
                "access_end_at",
                "supersedes_fact_id",
            ),
        ),
        "retirement": FactSpec(
            key="retirement",
            app_label="hr_exit",
            model_name="RetirementFact",
            as_of_field="effective_date",
            allowed_statuses=("EFFECTIVE", "REVISED", "REVOKED"),
            hash_fields=(
                "id",
                "fact_no",
                "person_id",
                "exit_fact_id",
                "retirement_type",
                "statutory_date",
                "effective_date",
                "supersedes_fact_id",
            ),
        ),
    },
)


def hr13_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR13_SPEC, **kwargs)


def hr14_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR14_SPEC, **kwargs)


def hr16_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR16_SPEC, **kwargs)
