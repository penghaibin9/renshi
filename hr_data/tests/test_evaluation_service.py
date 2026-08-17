import json
from datetime import date

from django.test import TestCase

from hr_data.models import MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.evaluation_service import (
    AsOfEvaluationError,
    Hr03AsOfEvaluationService,
)
from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffMaster


class Hr03HistoricalEvaluationTests(TestCase):
    def _staff(self, no):
        person = HrPerson.objects.create(tenant_id=77, legal_name=f"教师-{no}")
        return HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=person,
            staff_no=no,
            current_employment_status="ACTIVE",
        )

    def _relationship(
        self,
        staff,
        suffix,
        *,
        status="ACTIVE",
        employment_type="FULL_TIME",
        start=date(2025, 1, 1),
        end=None,
    ):
        return HrEmploymentRelationship.objects.create(
            tenant_id=77,
            staff_id=staff,
            employment_type=employment_type,
            effective_from=start,
            effective_to=end,
            status=status,
            source_business_type="TEST",
            source_business_id=f"{staff.staff_no}-{suffix}",
        )

    def _population(
        self,
        *,
        code,
        grain,
        predicate=None,
        sources=None,
        root_domain="HR03",
    ):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code=code,
            name=code,
            root_domain=root_domain,
            grain=grain,
            predicate_json=predicate
            or {"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=sources or ["HR03"],
            version_no=1,
            content_hash=(code.lower().encode().hex() + "0" * 64)[:64],
        )

    def setUp(self):
        staff_a = self._staff("T001")
        staff_b = self._staff("T002")
        self._relationship(staff_a, "A")
        self._relationship(staff_a, "B", employment_type="PART_TIME")
        self._relationship(staff_b, "A")

    def test_staff_grain_deduplicates_multiple_active_relationships(self):
        population = self._population(code="ACTIVE_STAFF", grain="STAFF")

        result = Hr03AsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-STAFF-20260801",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 2)
        self.assertEqual(result.grain, "STAFF")
        self.assertEqual(result.evidence.status, "COMPLETE")
        self.assertEqual(len(result.calculation_hash), 64)

    def test_relationship_grain_counts_each_active_relationship(self):
        population = self._population(
            code="ACTIVE_RELATIONSHIPS",
            grain="EMPLOYMENT_RELATIONSHIP",
        )

        result = Hr03AsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-REL-20260801",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 3)
        self.assertEqual(result.grain, "EMPLOYMENT_RELATIONSHIP")

    def test_asof_interval_and_predicate_are_applied_to_authoritative_segments(self):
        staff_c = self._staff("T003")
        self._relationship(
            staff_c,
            "ENDED",
            start=date(2025, 1, 1),
            end=date(2026, 7, 1),
        )
        population = self._population(
            code="FULL_TIME_ACTIVE",
            grain="STAFF",
            predicate={
                "and": [
                    {"field": "employment.status", "op": "eq", "value": "ACTIVE"},
                    {
                        "field": "employment.employmentType",
                        "op": "eq",
                        "value": "FULL_TIME",
                    },
                ]
            },
        )

        result = Hr03AsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-FULLTIME-20260801",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 2)

    def test_count_metric_uses_frozen_population_version_and_grain(self):
        population = self._population(code="ACTIVE_STAFF_METRIC_POP", grain="STAFF")
        metric = MetricDefinitionVersion.objects.create(
            tenant_id=77,
            metric_code="HEADCOUNT",
            name="在职人数",
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
            source_domains=["HR03"],
            version_no=1,
            content_hash="f" * 64,
        )

        result = Hr03AsOfEvaluationService(77).evaluate_count_metric(
            evidence_no="EV-HEADCOUNT-20260801",
            metric_code=metric.metric_code,
            metric_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(result.value, 2)
        self.assertEqual(result.definition_kind, "METRIC")
        self.assertEqual(result.population_code, population.population_code)
        self.assertEqual(result.grain, "STAFF")

    def test_legacy_unspecified_and_not_yet_supported_grains_fail_closed(self):
        legacy = self._population(code="LEGACY_POP", grain="UNSPECIFIED")
        person = self._population(code="PERSON_POP", grain="PERSON")
        assignment = self._population(code="ASSIGNMENT_POP", grain="ASSIGNMENT")

        for population in (legacy, person, assignment):
            with self.assertRaises(AsOfEvaluationError) as ctx:
                Hr03AsOfEvaluationService(77).evaluate_population(
                    evidence_no=f"EV-{population.population_code}",
                    population_code=population.population_code,
                    population_version=1,
                    as_of_date=date(2026, 8, 1),
                )
            self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_GRAIN_UNSUPPORTED")

    def test_multidomain_population_and_unsupported_field_never_fall_back_to_current_data(self):
        multidomain = self._population(
            code="MULTI_DOMAIN",
            grain="STAFF",
            sources=["HR03", "HR14"],
        )
        unsupported = self._population(
            code="CURRENT_STATUS",
            grain="STAFF",
            predicate={
                "field": "staff.currentEmploymentStatus",
                "op": "eq",
                "value": "ACTIVE",
            },
        )

        with self.assertRaises(AsOfEvaluationError) as ctx:
            Hr03AsOfEvaluationService(77).evaluate_population(
                evidence_no="EV-MULTI",
                population_code=multidomain.population_code,
                population_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_SOURCE_UNSUPPORTED")

        with self.assertRaises(AsOfEvaluationError) as ctx:
            Hr03AsOfEvaluationService(77).evaluate_population(
                evidence_no="EV-CURRENT",
                population_code=unsupported.population_code,
                population_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertIn(
            ctx.exception.code,
            {"ASOF_EVALUATION_EVIDENCE_INCOMPLETE", "ASOF_EVALUATION_FIELD_UNSUPPORTED"},
        )

    def test_frozen_evidence_cannot_be_reused_after_authoritative_history_changes(self):
        population = self._population(code="STALE_EVIDENCE", grain="STAFF")
        service = Hr03AsOfEvaluationService(77)
        first = service.evaluate_population(
            evidence_no="EV-STALE",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertEqual(first.value, 2)

        staff_c = self._staff("T003-LATE")
        self._relationship(staff_c, "LATE-BACKFILL", start=date(2025, 5, 1))

        with self.assertRaises(AsOfEvaluationError) as ctx:
            service.evaluate_population(
                evidence_no="EV-STALE",
                population_code=population.population_code,
                population_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_EVIDENCE_STALE")
