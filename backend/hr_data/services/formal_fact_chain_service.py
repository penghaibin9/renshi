"""Chain-aware HR13/HR14 historical formal-fact evaluation.

HR13 revisions/revocations are append-only and deliberately do not rewrite the
predecessor effective range.  Therefore historical value evaluation must select
the terminal fact in each chain *as of the requested date* before applying the
population predicate.  HR14 also uses successor facts; applying the same rule
keeps the evaluator correct even while a future successor exists.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Exists, OuterRef, Q

from hr_data.services.formal_fact_evaluation_service import (
    FormalDomainSpec,
    FormalFactAsOfEvaluationService as _BaseFormalFactAsOfEvaluationService,
    _compile_predicate,
)


_SUCCESSOR_FIELDS = {
    "HR13": "supersedes_result_id",
    "HR14": "supersedes_fact_id",
}

# Only a durable terminal successor may retire its predecessor.  HR14 may retain
# EFFECT_PENDING successor rows after a failed provider effect; those must never
# hide the still-effective source fact.
_SUPERSEDING_STATUSES = {
    "HR13": ("EFFECTIVE", "REVISED", "REVOKED"),
    "HR14": ("EFFECTIVE", "REVISED", "ENDED", "REVOKED"),
}


class FormalFactAsOfEvaluationService(_BaseFormalFactAsOfEvaluationService):
    """Canonical chain-aware formal-fact evaluator used by the HR18 router."""

    def _count(
        self,
        population,
        spec: FormalDomainSpec,
        as_of_date: date,
    ) -> int:
        model = self._model(spec)
        if model is None:
            from hr_data.services.evaluation_service import AsOfEvaluationError

            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
                f"{spec.domain} Authority app is not available in this integrated code tree",
            )

        successor_field = _SUCCESSOR_FIELDS[spec.domain]
        successors = model.objects.filter(
            tenant_id=self.tenant_id,
            effective_from__lte=as_of_date,
            status__in=_SUPERSEDING_STATUSES[spec.domain],
            **{successor_field: OuterRef("pk")},
        )
        queryset = (
            model.objects.filter(
                tenant_id=self.tenant_id,
                effective_from__lte=as_of_date,
            )
            .annotate(_hr18_has_effective_successor=Exists(successors))
            .filter(_hr18_has_effective_successor=False)
            .filter(status__in=spec.active_statuses)
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date))
            .filter(_compile_predicate(population.predicate_json, spec))
        )
        return queryset.values("person_id").distinct().count()
