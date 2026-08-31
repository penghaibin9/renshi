"""Safe authoring services for HR18 population and dimension definitions."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Max

from hr_data.models import DimensionDefinitionVersion, PopulationDefinitionVersion


class HrDataDefinitionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_PATH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")
_DOMAIN_RE = re.compile(r"^HR(?:0[1-9]|1[0-8])$")
_ALLOWED_LEAF_OPS = frozenset(
    {"eq", "ne", "in", "not_in", "is_null", "gte", "gt", "lte", "lt"}
)
_ALLOWED_VALUE_TYPES = frozenset(
    {"STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME", "CODE"}
)


def _canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _code(value, *, label: str) -> str:
    value = str(value or "").strip().upper()
    if not _CODE_RE.fullmatch(value):
        raise HrDataDefinitionError(
            "HR18_DEFINITION_CODE_INVALID",
            f"{label} must use uppercase letters, digits and underscores",
        )
    return value


def _domain(value, *, label: str) -> str:
    value = str(value or "").strip().upper()
    if not _DOMAIN_RE.fullmatch(value):
        raise HrDataDefinitionError(
            "HR18_SOURCE_DOMAIN_INVALID", f"{label} must be HR01..HR18"
        )
    return value


def _source_domains(values) -> list[str]:
    if not isinstance(values, list) or not values:
        raise HrDataDefinitionError(
            "HR18_SOURCE_DOMAINS_REQUIRED", "source_domains must be a non-empty list"
        )
    result = []
    for value in values:
        domain = _domain(value, label="source_domain")
        if domain not in result:
            result.append(domain)
    return result


def _population_grain(value) -> str:
    grain = str(value or "").strip().upper()
    allowed = set(PopulationDefinitionVersion.Grain.values) - {
        PopulationDefinitionVersion.Grain.UNSPECIFIED
    }
    if grain not in allowed:
        raise HrDataDefinitionError(
            "HR18_POPULATION_GRAIN_INVALID",
            "grain must be PERSON, STAFF, EMPLOYMENT_RELATIONSHIP or ASSIGNMENT",
        )
    return grain


def _validate_predicate(node, *, depth: int = 0) -> None:
    """Validate a small declarative filter grammar; no executable code allowed."""
    if depth > 8:
        raise HrDataDefinitionError(
            "HR18_POPULATION_PREDICATE_TOO_DEEP", "population predicate nesting is too deep"
        )
    if not isinstance(node, dict) or not node:
        raise HrDataDefinitionError(
            "HR18_POPULATION_PREDICATE_INVALID", "predicate nodes must be non-empty objects"
        )
    keys = set(node)
    logical = keys & {"and", "or", "not"}
    if logical:
        if len(logical) != 1 or keys != logical:
            raise HrDataDefinitionError(
                "HR18_POPULATION_PREDICATE_INVALID",
                "logical predicate node must contain exactly one of and/or/not",
            )
        key = next(iter(logical))
        value = node[key]
        if key == "not":
            _validate_predicate(value, depth=depth + 1)
            return
        if not isinstance(value, list) or not value:
            raise HrDataDefinitionError(
                "HR18_POPULATION_PREDICATE_INVALID",
                f"{key} must contain a non-empty list",
            )
        for child in value:
            _validate_predicate(child, depth=depth + 1)
        return

    if keys != {"field", "op", "value"}:
        raise HrDataDefinitionError(
            "HR18_POPULATION_PREDICATE_INVALID",
            "leaf predicate must contain field, op and value",
        )
    field = str(node["field"] or "").strip()
    op = str(node["op"] or "").strip().lower()
    if not _PATH_RE.fullmatch(field):
        raise HrDataDefinitionError(
            "HR18_POPULATION_FIELD_INVALID", "predicate field path is invalid"
        )
    if op not in _ALLOWED_LEAF_OPS:
        raise HrDataDefinitionError(
            "HR18_POPULATION_OPERATOR_INVALID", f"unsupported predicate operator: {op}"
        )
    if op in {"in", "not_in"} and not isinstance(node["value"], list):
        raise HrDataDefinitionError(
            "HR18_POPULATION_VALUE_INVALID", f"{op} requires a list value"
        )
    if op == "is_null" and not isinstance(node["value"], bool):
        raise HrDataDefinitionError(
            "HR18_POPULATION_VALUE_INVALID", "is_null requires a boolean value"
        )


@dataclass(frozen=True)
class DefinitionOutcome:
    definition: object
    created: bool


class HrDataDefinitionService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise HrDataDefinitionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def create_population_version(
        self,
        *,
        population_code: str,
        name: str,
        root_domain: str,
        grain: str,
        predicate: dict,
        source_domains: list,
        description: str = "",
        as_of_required: bool = True,
    ) -> DefinitionOutcome:
        code = _code(population_code, label="population_code")
        name = str(name or "").strip()
        if not name:
            raise HrDataDefinitionError("HR18_DEFINITION_NAME_REQUIRED", "name is required")
        root_domain = _domain(root_domain, label="root_domain")
        grain = _population_grain(grain)
        domains = _source_domains(source_domains)
        if root_domain not in domains:
            raise HrDataDefinitionError(
                "HR18_ROOT_DOMAIN_NOT_DECLARED",
                "root_domain must also appear in source_domains",
            )
        _validate_predicate(predicate)
        canonical = {
            "populationCode": code,
            "name": name,
            "description": str(description or "").strip(),
            "rootDomain": root_domain,
            "grain": grain,
            "predicate": predicate,
            "sourceDomains": domains,
            "asOfRequired": bool(as_of_required),
        }
        content_hash = _canonical_hash(canonical)
        existing = PopulationDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            population_code=code,
            content_hash=content_hash,
        ).order_by("-version_no").first()
        if existing is not None:
            return DefinitionOutcome(existing, False)
        version_no = (
            PopulationDefinitionVersion.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, population_code=code)
            .aggregate(v=Max("version_no"))["v"]
            or 0
        ) + 1
        definition = PopulationDefinitionVersion.objects.create(
            tenant_id=self.tenant_id,
            population_code=code,
            name=name,
            description=canonical["description"],
            root_domain=root_domain,
            grain=grain,
            predicate_json=predicate,
            source_domains=domains,
            as_of_required=bool(as_of_required),
            version_no=version_no,
            content_hash=content_hash,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return DefinitionOutcome(definition, True)

    @transaction.atomic
    def create_dimension_version(
        self,
        *,
        dimension_code: str,
        name: str,
        source_domain: str,
        attribute_path: str,
        value_type: str,
        label_map: Optional[dict] = None,
        description: str = "",
        as_of_required: bool = True,
    ) -> DefinitionOutcome:
        code = _code(dimension_code, label="dimension_code")
        name = str(name or "").strip()
        if not name:
            raise HrDataDefinitionError("HR18_DEFINITION_NAME_REQUIRED", "name is required")
        source_domain = _domain(source_domain, label="source_domain")
        attribute_path = str(attribute_path or "").strip()
        if not _PATH_RE.fullmatch(attribute_path):
            raise HrDataDefinitionError(
                "HR18_DIMENSION_PATH_INVALID", "attribute_path is invalid"
            )
        value_type = str(value_type or "").strip().upper()
        if value_type not in _ALLOWED_VALUE_TYPES:
            raise HrDataDefinitionError(
                "HR18_DIMENSION_VALUE_TYPE_INVALID", f"unsupported value_type: {value_type}"
            )
        label_map = {} if label_map is None else label_map
        if not isinstance(label_map, dict):
            raise HrDataDefinitionError(
                "HR18_DIMENSION_LABEL_MAP_INVALID", "label_map must be an object"
            )
        canonical = {
            "dimensionCode": code,
            "name": name,
            "description": str(description or "").strip(),
            "sourceDomain": source_domain,
            "attributePath": attribute_path,
            "valueType": value_type,
            "labelMap": label_map,
            "asOfRequired": bool(as_of_required),
        }
        content_hash = _canonical_hash(canonical)
        existing = DimensionDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            dimension_code=code,
            content_hash=content_hash,
        ).order_by("-version_no").first()
        if existing is not None:
            return DefinitionOutcome(existing, False)
        version_no = (
            DimensionDefinitionVersion.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, dimension_code=code)
            .aggregate(v=Max("version_no"))["v"]
            or 0
        ) + 1
        definition = DimensionDefinitionVersion.objects.create(
            tenant_id=self.tenant_id,
            dimension_code=code,
            name=name,
            description=canonical["description"],
            source_domain=source_domain,
            attribute_path=attribute_path,
            value_type=value_type,
            label_map_json=label_map,
            as_of_required=bool(as_of_required),
            version_no=version_no,
            content_hash=content_hash,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return DefinitionOutcome(definition, True)
