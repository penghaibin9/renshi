"""Route HR18 historical COUNT requests to bounded Authority-specific evaluators."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from hr_data.models import MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.assignment_evaluation_service import Hr03AssignmentAsOfEvaluationService
from hr_data.services.evaluation_service import (
    AsOfEvaluationError,
    AsOfEvaluationResult,
    Hr03AsOfEvaluationService,
)
from hr_data.services.formal_fact_evaluation_service import FormalFactAsOfEvaluationService


@dataclass(frozen=True)
class RoutedEvaluationResult:
    result: AsOfEvaluationResult
    evaluator_version: str


class HistoricalEvaluationRouter:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AsOfEvaluationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

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
        return population

    def _service_for_population(self, population: PopulationDefinitionVersion):
        domain = str(population.root_domain or "").strip().upper()
        sources = set(population.source_domains or [])
        if domain == "HR03" and sources == {"HR03"}:
            if population.grain == PopulationDefinitionVersion.Grain.ASSIGNMENT:
                return Hr03AssignmentAsOfEvaluationService(
                    self.tenant_id,
                    actor_user_id=self.actor_user_id,
                ), "hr03-assignment-count-v1"
            return Hr03AsOfEvaluationService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ), "hr03-count-v1"
        if domain in {"HR13", "HR14"} and sources == {domain}:
            return FormalFactAsOfEvaluationService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
            ), None
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_SOURCE_UNSUPPORTED",
            "historical value evaluator supports HR03, HR13 or HR14 single-domain populations only",
        )

    def evaluate_population(
        self,
        *,
        evidence_no: str,
        population_code: str,
        population_version: int,
        as_of_date: date,
    ) -> RoutedEvaluationResult:
        population = self._population(population_code, population_version)
        service, evaluator_version = self._service_for_population(population)
        if isinstance(service, FormalFactAsOfEvaluationService):
            result, version = service.evaluate_population(
                evidence_no=evidence_no,
                population_code=population.population_code,
                population_version=population.version_no,
                as_of_date=as_of_date,
            )
            return RoutedEvaluationResult(result, version)
        result = service.evaluate_population(
            evidence_no=evidence_no,
            population_code=population.population_code,
            population_version=population.version_no,
            as_of_date=as_of_date,
        )
        return RoutedEvaluationResult(result, evaluator_version)

    def evaluate_count_metric(
        self,
        *,
        evidence_no: str,
        metric_code: str,
        metric_version: int,
        as_of_date: date,
    ) -> RoutedEvaluationResult:
        metric = MetricDefinitionVersion.objects.filter(
            tenant_id=self.tenant_id,
            metric_code=str(metric_code or "").strip().upper(),
            version_no=int(metric_version),
        ).first()
        if metric is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_NOT_FOUND", "metric definition version not found"
            )
        try:
            expression = json.loads(metric.expression or "{}")
            population_version = int(expression.get("populationVersion"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_METRIC_EXPRESSION_INVALID", "metric expression is invalid"
            ) from exc
        population = self._population(metric.population_code, population_version)
        service, evaluator_version = self._service_for_population(population)
        if isinstance(service, FormalFactAsOfEvaluationService):
            result, version = service.evaluate_count_metric(
                evidence_no=evidence_no,
                metric_code=metric.metric_code,
                metric_version=metric.version_no,
                as_of_date=as_of_date,
            )
            return RoutedEvaluationResult(result, version)
        result = service.evaluate_count_metric(
            evidence_no=evidence_no,
            metric_code=metric.metric_code,
            metric_version=metric.version_no,
            as_of_date=as_of_date,
        )
        return RoutedEvaluationResult(result, evaluator_version)
