"""Bounded historical COUNT evaluator for formal HR06/HR07/HR12/HR13/HR14/HR16 facts.

The evaluator deliberately resolves sibling Authority models through Django's app
registry so the isolated HR18 branch has no import-time dependency on HR13/HR14.
Before integration the source remains unavailable; after branch integration the
same code evaluates only effective-dated formal facts, never mutable workflow
rows or legacy current-state projections.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from django.apps import apps
from django.db.models import Count, Q
from django.utils.dateparse import parse_date

from hr_data.models import AsOfEvidenceSnapshot, MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.evaluation_service import AsOfEvaluationError, AsOfEvaluationResult
from hr_data.services.asof_service import AsOfReconstructionService


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class FormalDomainSpec:
    domain: str
    app_label: str
    model_name: str
    evaluator_version: str
    active_statuses: tuple[str, ...]
    field_map: dict[str, tuple[str, str]]
    grain: str = PopulationDefinitionVersion.Grain.PERSON
    identity_field: str = "person_id"


def _normalize_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


def _coerce(value: Any, value_type: str):
    if value_type == "DATE":
        if isinstance(value, date):
            return value
        parsed = parse_date(str(value or "").strip())
        if parsed is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "date predicate value must be YYYY-MM-DD"
            )
        return parsed
    if value_type == "UUID":
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "UUID predicate value is invalid"
            ) from exc
    if value_type == "DECIMAL":
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "decimal predicate value is invalid"
            ) from exc
    if value_type == "INTEGER":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "integer predicate value is invalid"
            ) from exc
    return value


def _compile_leaf(node: dict, spec: FormalDomainSpec) -> Q:
    path = _normalize_path(node.get("field"))
    mapping = spec.field_map.get(path)
    if mapping is None:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_FIELD_UNSUPPORTED",
            f"historical {spec.domain} evaluator does not support field: {node.get('field')}",
        )
    field_name, value_type = mapping
    op = str(node.get("op") or "").strip().lower()
    value = node.get("value")
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
        values = [_coerce(item, value_type) for item in value]
        query = Q(**{f"{field_name}__in": values})
        return ~query if op == "not_in" else query
    coerced = _coerce(value, value_type)
    if op == "eq":
        return Q(**{field_name: coerced})
    if op == "ne":
        return ~Q(**{field_name: coerced})
    if op in {"gte", "gt", "lte", "lt"}:
        return Q(**{f"{field_name}__{op}": coerced})
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_OPERATOR_UNSUPPORTED", f"unsupported operator: {op}"
    )


def _compile_predicate(node, spec: FormalDomainSpec) -> Q:
    if not isinstance(node, dict) or not node:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate is invalid"
        )
    keys = set(node)
    if keys == {"field", "op", "value"}:
        return _compile_leaf(node, spec)
    if keys == {"and"}:
        children = node["and"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "and requires a non-empty list"
            )
        query = Q()
        for child in children:
            query &= _compile_predicate(child, spec)
        return query
    if keys == {"or"}:
        children = node["or"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "or requires a non-empty list"
            )
        query = Q(pk__in=[])
        for child in children:
            query |= _compile_predicate(child, spec)
        return query
    if keys == {"not"}:
        return ~_compile_predicate(node["not"], spec)
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate structure is invalid"
    )



HR04_SPEC = FormalDomainSpec(
    domain="HR04",
    app_label="hr_recruitment",
    model_name="HrHiringDecisionFact",
    evaluator_version="hr04-hiring-person-count-v1",
    active_statuses=("EFFECTIVE", "CORRECTED"),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "hiring.candidateId": ("candidateId", "UUID"),
            "hiring.recruitmentPositionId": ("recruitmentPositionId", "UUID"),
            "hiring.offerNo": ("offerNo", "STRING"),
            "hiring.rank": ("rank", "INTEGER"),
            "hiring.finalScore": ("finalScore", "DECIMAL"),
            "hiring.employmentType": ("employmentType", "STRING"),
            "hiring.expectedReportDate": ("expectedReportDate", "DATE"),
            "hiring.acceptedAt": ("acceptedAt", "DATE"),
            "hiring.status": ("status", "STRING"),
        }.items()
    },
    grain=PopulationDefinitionVersion.Grain.PERSON,
    identity_field="candidateId",
)

HR05_SPEC = FormalDomainSpec(
    domain="HR05",
    app_label="hr_onboarding",
    model_name="HrOnboardingActivationSnapshot",
    evaluator_version="hr05-activation-staff-count-v1",
    active_statuses=("EFFECTIVE",),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "onboarding.personId": ("personId", "UUID"),
            "onboarding.staffMasterId": ("staffMasterId", "UUID"),
            "onboarding.employmentId": ("employmentId", "UUID"),
            "onboarding.assignmentId": ("assignmentId", "UUID"),
            "onboarding.staffNo": ("staffNo", "STRING"),
            "onboarding.organizationId": ("organizationId", "INTEGER"),
            "onboarding.positionId": ("positionId", "INTEGER"),
            "onboarding.sourceType": ("sourceType", "STRING"),
            "onboarding.sourceId": ("sourceId", "STRING"),
            "onboarding.activatedAt": ("activatedAt", "DATE"),
            "onboarding.status": ("status", "STRING"),
        }.items()
    },
    grain=PopulationDefinitionVersion.Grain.STAFF,
    identity_field="staffMasterId",
)

HR15_SPEC = FormalDomainSpec(
    domain="HR15",
    app_label="hr_payroll",
    model_name="PayrollResultFact",
    evaluator_version="hr15-payroll-staff-count-v1",
    active_statuses=("FINALIZED", "ADJUSTED"),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "payroll.resultId": ("resultId", "UUID"),
            "payroll.periodId": ("periodId", "UUID"),
            "payroll.periodCode": ("periodCode", "STRING"),
            "payroll.staffId": ("staffId", "UUID"),
            "payroll.currencyCode": ("currencyCode", "STRING"),
            "payroll.grossAmount": ("grossAmount", "DECIMAL"),
            "payroll.deductionAmount": ("deductionAmount", "DECIMAL"),
            "payroll.netAmount": ("netAmount", "DECIMAL"),
            "payroll.status": ("status", "STRING"),
            "payroll.effectiveAt": ("effectiveAt", "DATE"),
        }.items()
    },
    grain=PopulationDefinitionVersion.Grain.STAFF,
    identity_field="staffId",
)


HR06_SPEC = FormalDomainSpec(
    domain="HR06",
    app_label="hr_changes",
    model_name="HrChangeEffectiveSnapshot",
    evaluator_version="hr06-change-staff-count-v1",
    active_statuses=(),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "change.staffId": ("change_case_id__staff_master_id", "UUID"),
            "change.actionCode": ("change_case_id__action_id__code", "STRING"),
            "change.reasonCode": ("change_case_id__reason_id__code", "STRING"),
            "change.sourceOrgId": ("change_case_id__source_org_id_id", "INTEGER"),
            "change.targetOrgId": ("change_case_id__target_org_id_id", "INTEGER"),
            "change.sourcePositionId": ("change_case_id__source_position_id_id", "INTEGER"),
            "change.targetPositionId": ("change_case_id__target_position_id_id", "INTEGER"),
            "change.effectiveDate": ("effective_at", "DATE"),
        }.items()
    },
    grain=PopulationDefinitionVersion.Grain.STAFF,
    identity_field="change_case_id__staff_master_id",
)

HR07_SPEC = FormalDomainSpec(
    domain="HR07",
    app_label="hr_contracts",
    model_name="HrContractVersion",
    evaluator_version="hr07-contract-staff-count-v1",
    active_statuses=("EFFECTIVE", "SUPERSEDED", "TERMINATED", "EXPIRED"),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "contract.staffId": ("agreement__staff_id", "UUID"),
            "contract.employmentRelationshipId": ("agreement__employment_relationship_id", "UUID"),
            "contract.agreementType": ("agreement__agreement_type", "STRING"),
            "contract.subjectType": ("agreement__subject_type", "STRING"),
            "contract.versionType": ("version_type", "STRING"),
            "contract.effectiveFrom": ("effective_from", "DATE"),
            "contract.effectiveTo": ("effective_to", "DATE"),
            "contract.status": ("status", "STRING"),
        }.items()
    },
    grain=PopulationDefinitionVersion.Grain.STAFF,
    identity_field="agreement__staff_id",
)


HR12_SPEC = FormalDomainSpec(
    domain="HR12",
    app_label="hr_assessment",
    model_name="HrFinalAssessmentResult",
    evaluator_version="hr12-assessment-staff-count-v1",
    active_statuses=("FINALIZED", "CORRECTED"),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "assessment.resultId": ("resultId", "UUID"),
            "assessment.staffId": ("staffId", "UUID"),
            "assessment.assessmentType": ("assessmentType", "STRING"),
            "assessment.cycleId": ("cycleId", "UUID"),
            "assessment.gradeCode": ("gradeCode", "STRING"),
            "assessment.status": ("status", "STRING"),
            "assessment.finalizedAt": ("finalizedAt", "DATE"),
        }.items()
    },
    grain=PopulationDefinitionVersion.Grain.STAFF,
    identity_field="staffId",
)

HR13_SPEC = FormalDomainSpec(
    domain="HR13",
    app_label="hr_title",
    model_name="ProfessionalTitleResult",
    evaluator_version="hr13-title-person-count-v1",
    active_statuses=("EFFECTIVE", "REVISED"),
    field_map={
        **{
            _normalize_path(field): mapping
            for field, mapping in {
                "title.personId": ("person_id", "UUID"),
                "title.titleCode": ("title_code", "STRING"),
                "title.titleName": ("title_name", "STRING"),
                "title.titleSeriesCode": ("title_series_code", "STRING"),
                "title.titleLevelCode": ("title_level_code", "STRING"),
                "title.effectiveFrom": ("effective_from", "DATE"),
                "title.effectiveTo": ("effective_to", "DATE"),
                "title.status": ("status", "STRING"),
            }.items()
        },
        **{
            _normalize_path(field.replace("title.", "professionalTitle.")): mapping
            for field, mapping in {
                "title.personId": ("person_id", "UUID"),
                "title.titleCode": ("title_code", "STRING"),
                "title.titleName": ("title_name", "STRING"),
                "title.titleSeriesCode": ("title_series_code", "STRING"),
                "title.titleLevelCode": ("title_level_code", "STRING"),
                "title.effectiveFrom": ("effective_from", "DATE"),
                "title.effectiveTo": ("effective_to", "DATE"),
                "title.status": ("status", "STRING"),
            }.items()
        },
    },
)

HR14_SPEC = FormalDomainSpec(
    domain="HR14",
    app_label="hr_appointment",
    model_name="PositionAppointmentFact",
    evaluator_version="hr14-appointment-person-count-v1",
    active_statuses=("EFFECTIVE", "REVISED"),
    field_map={
        _normalize_path(field): mapping
        for field, mapping in {
            "appointment.personId": ("person_id", "UUID"),
            "appointment.positionInstanceId": ("position_instance_id", "INTEGER"),
            "appointment.levelCode": ("level_code", "STRING"),
            "appointment.effectiveFrom": ("effective_from", "DATE"),
            "appointment.effectiveTo": ("effective_to", "DATE"),
            "appointment.status": ("status", "STRING"),
        }.items()
    },
)

HR16_SPEC = FormalDomainSpec(
    domain="HR16", app_label="hr_exit", model_name="RetirementFact",
    evaluator_version="hr16-retirement-person-count-v1", active_statuses=("EFFECTIVE", "REVISED"),
    field_map={_normalize_path(field): mapping for field, mapping in {
        "retirement.personId": ("person_id", "UUID"),
        "retirement.retirementType": ("retirement_type", "STRING"),
        "retirement.statutoryDate": ("statutory_date", "DATE"),
        "retirement.effectiveDate": ("effective_date", "DATE"),
    }.items()},
)
SPECS = {spec.domain: spec for spec in (HR04_SPEC, HR05_SPEC, HR06_SPEC, HR07_SPEC, HR12_SPEC, HR13_SPEC, HR14_SPEC, HR15_SPEC, HR16_SPEC)}


class FormalFactAsOfEvaluationService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AsOfEvaluationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _population(self, code: str, version: int) -> tuple[PopulationDefinitionVersion, FormalDomainSpec]:
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
        if not _HASH_RE.fullmatch(str(population.content_hash or "")):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_DEFINITION_HASH_INVALID",
                "population definition must have a frozen content hash",
            )
        domain = str(population.root_domain or "").strip().upper()
        spec = SPECS.get(domain)
        if spec is None or set(population.source_domains or []) != {domain}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "formal fact evaluator supports single-domain HR04, HR05, HR06, HR07, HR12, HR13, HR14, HR15 or HR16 formal-fact populations",
            )
        if population.grain != spec.grain:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_GRAIN_UNSUPPORTED",
                f"{spec.domain} formal fact evaluator requires {spec.grain} grain",
            )
        return population, spec

    @staticmethod
    def _model(spec: FormalDomainSpec):
        try:
            return apps.get_model(spec.app_label, spec.model_name)
        except LookupError:
            return None

    def _count(self, population: PopulationDefinitionVersion, spec: FormalDomainSpec, as_of_date: date) -> int:
        if spec.domain in {"HR04", "HR05", "HR06", "HR12", "HR15", "HR16"}:
            from hr_data.services.formal_fact_chain_service import FormalFactAsOfEvaluationService as ChainService
            return ChainService(self.tenant_id, self.actor_user_id)._count(population, spec, as_of_date)
        model = self._model(spec)
        if model is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
                f"{spec.domain} Authority app is not available in this integrated code tree",
            )
        queryset = (
            model.objects.filter(
                tenant_id=self.tenant_id,
                effective_from__lte=as_of_date,
                status__in=spec.active_statuses,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
        )
        if spec.domain == "HR07":
            queryset = queryset.filter(agreement__tenant_id=self.tenant_id)
            if queryset.values("agreement_id").annotate(_hr18_n=Count("id")).filter(_hr18_n__gt=1).exists():
                raise AsOfEvaluationError(
                    "ASOF_EVALUATION_SOURCE_CONFLICT",
                    "multiple formal HR07 contract versions overlap the requested as-of date",
                )
        queryset = queryset.filter(_compile_predicate(population.predicate_json, spec))
        return queryset.exclude(**{f"{spec.identity_field}__isnull": True}).values(spec.identity_field).distinct().count()

    @staticmethod
    def _calculation_hash(
        *, definition_hash: str, evidence_hash: str, value: int, evaluator_version: str, grain: str
    ) -> str:
        raw = json.dumps(
            {
                "definitionHash": definition_hash.lower(),
                "evidenceHash": evidence_hash.lower(),
                "value": value,
                "grain": grain,
                "evaluatorVersion": evaluator_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _evidence(
        self,
        *,
        evidence_no: str,
        definition_kind: str,
        definition_code: str,
        definition_version: int,
        as_of_date: date,
    ) -> AsOfEvidenceSnapshot:
        evidence = AsOfReconstructionService(
            self.tenant_id,
            actor_user_id=self.actor_user_id,
        ).reconstruct(
            evidence_no=evidence_no,
            definition_kind=definition_kind,
            definition_code=definition_code,
            definition_version=definition_version,
            as_of_date=as_of_date,
        ).evidence
        if evidence.status != AsOfEvidenceSnapshot.Status.COMPLETE:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_EVIDENCE_INCOMPLETE",
                f"as-of evidence status {evidence.status} cannot produce a formal value",
            )
        return evidence

    def evaluate_population(
        self,
        *,
        evidence_no: str,
        population_code: str,
        population_version: int,
        as_of_date: date,
    ) -> tuple[AsOfEvaluationResult, str]:
        if not isinstance(as_of_date, date):
            raise AsOfEvaluationError("ASOF_EVALUATION_DATE_INVALID", "as_of_date must be a date")
        population, spec = self._population(population_code, population_version)
        evidence = self._evidence(
            evidence_no=evidence_no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.POPULATION,
            definition_code=population.population_code,
            definition_version=population.version_no,
            as_of_date=as_of_date,
        )
        value = self._count(population, spec, as_of_date)
        result = AsOfEvaluationResult(
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.POPULATION,
            definition_code=population.population_code,
            definition_version=population.version_no,
            as_of_date=as_of_date,
            population_code=population.population_code,
            population_version=population.version_no,
            grain=population.grain,
            value=value,
            evidence=evidence,
            calculation_hash=self._calculation_hash(
                definition_hash=population.content_hash,
                evidence_hash=evidence.evidence_hash,
                value=value,
                evaluator_version=spec.evaluator_version,
                grain=population.grain,
            ),
        )
        return result, spec.evaluator_version

    def evaluate_count_metric(
        self,
        *,
        evidence_no: str,
        metric_code: str,
        metric_version: int,
        as_of_date: date,
    ) -> tuple[AsOfEvaluationResult, str]:
        metric = MetricDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            metric_code=str(metric_code or "").strip().upper(),
            version_no=int(metric_version),
        ).first()
        if metric is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_NOT_FOUND", "metric definition version not found"
            )
        if not _HASH_RE.fullmatch(str(metric.content_hash or "")):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_DEFINITION_HASH_INVALID",
                "metric definition must have a frozen content hash",
            )
        try:
            expression = json.loads(metric.expression or "{}")
            population_version = int(expression.get("populationVersion"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_EXPRESSION_INVALID", "metric expression is invalid"
            ) from exc
        if expression.get("op") != "COUNT" or expression.get("field") not in (None, ""):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_UNSUPPORTED",
                "formal fact historical metric evaluator supports COUNT only",
            )
        population, spec = self._population(metric.population_code, population_version)
        if set(metric.source_domains or []) != {spec.domain}:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
                "metric and population must use the same single formal-fact domain",
            )
        evidence = self._evidence(
            evidence_no=evidence_no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=metric.metric_code,
            definition_version=metric.version_no,
            as_of_date=as_of_date,
        )
        value = self._count(population, spec, as_of_date)
        result = AsOfEvaluationResult(
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=metric.metric_code,
            definition_version=metric.version_no,
            as_of_date=as_of_date,
            population_code=population.population_code,
            population_version=population.version_no,
            grain=population.grain,
            value=value,
            evidence=evidence,
            calculation_hash=self._calculation_hash(
                definition_hash=metric.content_hash,
                evidence_hash=evidence.evidence_hash,
                value=value,
                evaluator_version=spec.evaluator_version,
                grain=population.grain,
            ),
        )
        return result, spec.evaluator_version
