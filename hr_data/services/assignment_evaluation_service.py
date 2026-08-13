"""HR03 assignment-grain historical COUNT evaluation for HR18.

This extends the existing HR03 evaluator without widening its source-of-truth
contract: only effective-dated ``HrStaffAssignment`` authority rows are queried.
Unsupported fields/domains still fail closed and frozen evidence is revalidated
before a formal value is returned.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.db.models import Q

from hr_data.models import PopulationDefinitionVersion
from hr_data.services.evaluation_service import (
    AsOfEvaluationError,
    Hr03AsOfEvaluationService,
    _coerce_scalar,
    _normalize_path,
)
from hr_staff.models import HrStaffAssignment


_ASSIGNMENT_FIELD_MAP = {
    "assignment.organizationid": ("organization_id_id", "UUID"),
    "assignment.positionid": ("position_id_id", "UUID"),
    "assignment.postcatalogid": ("post_catalog_id_id", "UUID"),
    "assignment.assignmenttype": ("assignment_type", "STRING"),
    "assignment.rolecode": ("assignment_role_code", "STRING"),
    "assignment.fte": ("fte", "DECIMAL"),
    "assignment.effectivefrom": ("effective_from", "DATE"),
    "assignment.effectiveto": ("effective_to", "DATE"),
    "assignment.status": ("status", "STRING"),
    "assignment.reportingstaffid": ("reporting_staff_id_id", "UUID"),
}


def _assignment_leaf(node: dict) -> Q:
    path = _normalize_path(node.get("field"))
    mapping = _ASSIGNMENT_FIELD_MAP.get(path)
    if mapping is None:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_FIELD_UNSUPPORTED",
            f"historical HR03 assignment evaluator does not support field: {node.get('field')}",
        )
    field_name, value_type = mapping
    op = str(node.get("op") or "").strip().lower()
    value = node.get("value")
    if value_type == "DECIMAL":
        try:
            from decimal import Decimal, InvalidOperation

            value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "decimal predicate value is invalid"
            ) from exc
        value_type = "STRING"
    if op == "is_null":
        if not isinstance(value, bool):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "is_null requires a boolean value"
            )
        return Q(**{f"{field_name}__isnull": value})
    if op in {"in", "not_in"}:
        if not isinstance(value, list):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", f"{op} requires a list value"
            )
        values = [_coerce_scalar(item, value_type) for item in value]
        query = Q(**{f"{field_name}__in": values})
        return ~query if op == "not_in" else query
    coerced = _coerce_scalar(value, value_type)
    if op == "eq":
        return Q(**{field_name: coerced})
    if op == "ne":
        return ~Q(**{field_name: coerced})
    if op in {"gte", "gt", "lte", "lt"}:
        return Q(**{f"{field_name}__{op}": coerced})
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_OPERATOR_UNSUPPORTED", f"unsupported operator: {op}"
    )


def _assignment_predicate(node) -> Q:
    if not isinstance(node, dict) or not node:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate is invalid"
        )
    keys = set(node)
    if keys == {"field", "op", "value"}:
        return _assignment_leaf(node)
    if keys == {"and"}:
        children = node["and"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "and requires a non-empty list"
            )
        query = Q()
        for child in children:
            query &= _assignment_predicate(child)
        return query
    if keys == {"or"}:
        children = node["or"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "or requires a non-empty list"
            )
        query = Q(pk__in=[])
        for child in children:
            query |= _assignment_predicate(child)
        return query
    if keys == {"not"}:
        return ~_assignment_predicate(node["not"])
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate structure is invalid"
    )


class Hr03AssignmentAsOfEvaluationService(Hr03AsOfEvaluationService):
    SUPPORTED_GRAINS = {PopulationDefinitionVersion.Grain.ASSIGNMENT}

    def _population(self, code: str, version: int) -> PopulationDefinitionVersion:
        population = PopulationDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            population_code=str(code or "").strip().upper(),
            version_no=int(version),
        ).first()
        if population is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_POPULATION_NOT_FOUND",
                "population definition version does not exist in current tenant",
            )
        import re

        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(population.content_hash or "")):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_DEFINITION_HASH_INVALID",
                "population definition must have a frozen content hash",
            )
        if population.root_domain != "HR03" or set(population.source_domains or []) != {"HR03"}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "assignment historical evaluator only supports HR03-only populations",
            )
        if population.grain != PopulationDefinitionVersion.Grain.ASSIGNMENT:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_GRAIN_UNSUPPORTED",
                "assignment evaluator requires ASSIGNMENT grain",
            )
        return population

    @staticmethod
    def _base_queryset(tenant_id: int, as_of_date: date):
        return (
            HrStaffAssignment.objects.filter(
                tenant_id=tenant_id,
                effective_from__lte=as_of_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .exclude(status__in=("DRAFT", "CANCELLED"))
        )

    def _count_population(self, population: PopulationDefinitionVersion, as_of_date: date) -> int:
        return self._base_queryset(self.tenant_id, as_of_date).filter(
            _assignment_predicate(population.predicate_json)
        ).count()

    @staticmethod
    def _calculation_hash(*, definition_hash: str, evidence_hash: str, value: int, grain: str) -> str:
        raw = json.dumps(
            {
                "definitionHash": definition_hash.lower(),
                "evidenceHash": evidence_hash.lower(),
                "value": value,
                "grain": grain,
                "evaluatorVersion": "hr03-assignment-count-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
