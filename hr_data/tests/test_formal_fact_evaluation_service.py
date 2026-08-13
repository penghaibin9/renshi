import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_data.models import MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.evaluation_router import HistoricalEvaluationRouter
from hr_data.services.evaluation_service import AsOfEvaluationError
from hr_data.services.formal_fact_evaluation_service import FormalFactAsOfEvaluationService


class FormalFactHistoricalEvaluationTests(TestCase):
    def _population(
        self,
        *,
        code,
        domain,
        field,
        value,
        grain="PERSON",
    ):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code=code,
            name=code,
            root_domain=domain,
            grain=grain,
            predicate_json={"field": field, "op": "eq", "value": value},
            source_domains=[domain],
            version_no=1,
            content_hash="a" * 64,
        )

    @staticmethod
    def _complete_evidence(no="EV-FORMAL"):
        return SimpleNamespace(
            status="COMPLETE",
            evidence_hash="e" * 64,
            evidence_no=no,
            id="00000000-0000-0000-0000-000000000099",
        )

    @staticmethod
    def _model_counting(value):
        model = SimpleNamespace(objects=MagicMock())
        first = MagicMock()
        interval = MagicMock()
        predicate = MagicMock()
        values = MagicMock()
        distinct = MagicMock()
        model.objects.filter.return_value = first
        first.filter.return_value = interval
        interval.filter.return_value = predicate
        predicate.values.return_value = values
        values.distinct.return_value = distinct
        distinct.count.return_value = value
        return model, first, interval, predicate, values, distinct

    def test_unmerged_hr13_authority_never_fakes_a_value(self):
        population = self._population(
            code="TITLE_HOLDERS_UNMERGED",
            domain="HR13",
            field="title.titleLevelCode",
            value="SENIOR",
        )

        with self.assertRaises(AsOfEvaluationError) as ctx:
            FormalFactAsOfEvaluationService(77).evaluate_population(
                evidence_no="EV-HR13-UNMERGED",
                population_code=population.population_code,
                population_version=1,
                as_of_date=date(2026, 8, 1),
            )

        self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_EVIDENCE_INCOMPLETE")

    @patch("hr_data.services.formal_fact_evaluation_service.apps.get_model")
    @patch(
        "hr_data.services.formal_fact_evaluation_service.AsOfReconstructionService.reconstruct"
    )
    def test_hr13_person_count_uses_effective_interval_and_active_terminal_facts(
        self, reconstruct, get_model
    ):
        population = self._population(
            code="SENIOR_TITLE_HOLDERS",
            domain="HR13",
            field="title.titleLevelCode",
            value="SENIOR",
        )
        reconstruct.return_value = SimpleNamespace(evidence=self._complete_evidence("EV-HR13"))
        model, first, _interval, _predicate, _values, distinct = self._model_counting(12)
        get_model.return_value = model

        result, version = FormalFactAsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-HR13",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 12)
        self.assertEqual(result.grain, "PERSON")
        self.assertEqual(version, "hr13-title-person-count-v1")
        get_model.assert_called_once_with("hr_title", "ProfessionalTitleResult")
        model.objects.filter.assert_called_once_with(
            tenant_id=77,
            effective_from__lte=date(2026, 8, 1),
            status__in=("EFFECTIVE", "REVISED"),
        )
        self.assertEqual(first.filter.call_count, 1)
        distinct.count.assert_called_once_with()
        self.assertEqual(len(result.calculation_hash), 64)

    @patch("hr_data.services.formal_fact_evaluation_service.apps.get_model")
    @patch(
        "hr_data.services.formal_fact_evaluation_service.AsOfReconstructionService.reconstruct"
    )
    def test_hr14_person_count_reads_only_effective_appointment_facts(
        self, reconstruct, get_model
    ):
        population = self._population(
            code="LEVEL_L7_APPOINTMENTS",
            domain="HR14",
            field="appointment.levelCode",
            value="L7",
        )
        reconstruct.return_value = SimpleNamespace(evidence=self._complete_evidence("EV-HR14"))
        model, _first, _interval, _predicate, _values, _distinct = self._model_counting(8)
        get_model.return_value = model

        result, version = FormalFactAsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-HR14",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 8)
        self.assertEqual(version, "hr14-appointment-person-count-v1")
        get_model.assert_called_once_with("hr_appointment", "PositionAppointmentFact")
        model.objects.filter.assert_called_once_with(
            tenant_id=77,
            effective_from__lte=date(2026, 8, 1),
            status__in=("EFFECTIVE", "REVISED"),
        )

    @patch("hr_data.services.formal_fact_evaluation_service.apps.get_model")
    @patch(
        "hr_data.services.formal_fact_evaluation_service.AsOfReconstructionService.reconstruct"
    )
    def test_formal_count_metric_uses_frozen_population_and_same_domain(
        self, reconstruct, get_model
    ):
        population = self._population(
            code="TITLE_POP",
            domain="HR13",
            field="professionalTitle.status",
            value="EFFECTIVE",
        )
        metric = MetricDefinitionVersion.objects.create(
            tenant_id=77,
            metric_code="TITLE_HOLDER_COUNT",
            name="职称持有人数",
            value_type="INTEGER",
            unit="人",
            population_code=population.population_code,
            expression=json.dumps(
                {
                    "dslVersion": "1",
                    "populationVersion": 1,
                    "op": "COUNT",
                    "field": None,
                }
            ),
            source_domains=["HR13"],
            version_no=1,
            content_hash="f" * 64,
        )
        reconstruct.return_value = SimpleNamespace(evidence=self._complete_evidence("EV-METRIC"))
        model, *_ = self._model_counting(21)
        get_model.return_value = model

        result, version = FormalFactAsOfEvaluationService(77).evaluate_count_metric(
            evidence_no="EV-METRIC",
            metric_code=metric.metric_code,
            metric_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 21)
        self.assertEqual(result.definition_kind, "METRIC")
        self.assertEqual(version, "hr13-title-person-count-v1")

    def test_hr16_and_non_person_grains_remain_fail_closed(self):
        hr16 = self._population(
            code="RETIRED_PEOPLE",
            domain="HR16",
            field="retirement.personId",
            value="00000000-0000-0000-0000-000000000001",
        )
        assignment = self._population(
            code="TITLE_ASSIGNMENT_GRAIN",
            domain="HR13",
            field="title.status",
            value="EFFECTIVE",
            grain="ASSIGNMENT",
        )

        for population, code in (
            (hr16, "ASOF_EVALUATION_SOURCE_UNSUPPORTED"),
            (assignment, "ASOF_EVALUATION_GRAIN_UNSUPPORTED"),
        ):
            with self.assertRaises(AsOfEvaluationError) as ctx:
                FormalFactAsOfEvaluationService(77)._population(
                    population.population_code,
                    1,
                )
            self.assertEqual(ctx.exception.code, code)


class HistoricalEvaluationRouterTests(TestCase):
    def _population(self, *, code, domain, grain, field):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code=code,
            name=code,
            root_domain=domain,
            grain=grain,
            predicate_json={"field": field, "op": "eq", "value": "ACTIVE"},
            source_domains=[domain],
            version_no=1,
            content_hash="c" * 64,
        )

    def test_router_selects_assignment_and_formal_fact_evaluators(self):
        assignment = self._population(
            code="ACTIVE_ASSIGNMENTS",
            domain="HR03",
            grain="ASSIGNMENT",
            field="assignment.status",
        )
        title = self._population(
            code="ACTIVE_TITLES",
            domain="HR13",
            grain="PERSON",
            field="title.status",
        )
        router = HistoricalEvaluationRouter(77)

        assignment_service, assignment_version = router._service_for_population(assignment)
        formal_service, formal_version = router._service_for_population(title)

        self.assertEqual(
            assignment_service.__class__.__name__,
            "Hr03AssignmentAsOfEvaluationService",
        )
        self.assertEqual(assignment_version, "hr03-assignment-count-v1")
        self.assertEqual(formal_service.__class__.__name__, "FormalFactAsOfEvaluationService")
        self.assertIsNone(formal_version)

    def test_router_rejects_hr16_event_population(self):
        population = self._population(
            code="EXIT_EVENTS",
            domain="HR16",
            grain="PERSON",
            field="exit.exitType",
        )
        with self.assertRaises(AsOfEvaluationError) as ctx:
            HistoricalEvaluationRouter(77)._service_for_population(population)
        self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_SOURCE_UNSUPPORTED")
