import json
from datetime import date
from decimal import Decimal

from django.test import TestCase

from hr_data.models import MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.assignment_evaluation_service import (
    Hr03AssignmentAsOfEvaluationService,
)
from hr_data.services.evaluation_service import AsOfEvaluationError
from hr_staff.models import (
    HrEmploymentRelationship,
    HrPerson,
    HrStaffAssignment,
    HrStaffMaster,
)


class Hr03AssignmentHistoricalEvaluationTests(TestCase):
    def _staff(self, no):
        person = HrPerson.objects.create(tenant_id=77, legal_name=f"教师-{no}")
        return HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=person,
            staff_no=no,
            current_employment_status="ACTIVE",
        )

    def _relationship(self, staff, suffix):
        return HrEmploymentRelationship.objects.create(
            tenant_id=77,
            staff_id=staff,
            employment_type="FULL_TIME",
            effective_from=date(2025, 1, 1),
            status="ACTIVE",
            source_business_type="TEST",
            source_business_id=f"{staff.staff_no}-{suffix}",
        )

    def _assignment(
        self,
        relationship,
        *,
        assignment_type="PRIMARY",
        fte="1.00",
        start=date(2025, 1, 1),
        end=None,
        status="ACTIVE",
        suffix="A",
    ):
        return HrStaffAssignment.objects.create(
            tenant_id=77,
            employment_relationship_id=relationship,
            assignment_type=assignment_type,
            assignment_role_code="TEACHER",
            fte=Decimal(fte),
            effective_from=start,
            effective_to=end,
            status=status,
            source_business_type="TEST",
            source_business_id=f"{relationship.id}-{suffix}"[:64],
        )

    def _population(self, code, predicate):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code=code,
            name=code,
            root_domain="HR03",
            grain=PopulationDefinitionVersion.Grain.ASSIGNMENT,
            predicate_json=predicate,
            source_domains=["HR03"],
            version_no=1,
            content_hash=(code.lower().encode().hex() + "0" * 64)[:64],
        )

    def setUp(self):
        rel_a = self._relationship(self._staff("T-A"), "REL")
        rel_b = self._relationship(self._staff("T-B"), "REL")
        rel_c = self._relationship(self._staff("T-C"), "REL")
        self._assignment(rel_a, assignment_type="PRIMARY", fte="1.00", suffix="A")
        self._assignment(rel_b, assignment_type="CONCURRENT", fte="0.50", suffix="B")
        self._assignment(
            rel_c,
            assignment_type="PRIMARY",
            fte="1.00",
            start=date(2025, 1, 1),
            end=date(2026, 7, 1),
            suffix="C",
        )

    def test_assignment_grain_counts_only_effective_dated_authority_rows(self):
        population = self._population(
            "ACTIVE_ASSIGNMENTS",
            {"field": "assignment.status", "op": "eq", "value": "ACTIVE"},
        )
        result = Hr03AssignmentAsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-ASSIGNMENT-20260801",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertEqual(result.value, 2)
        self.assertEqual(result.grain, "ASSIGNMENT")
        self.assertEqual(result.evidence.status, "COMPLETE")
        self.assertEqual(len(result.calculation_hash), 64)

    def test_assignment_predicates_support_type_and_decimal_fte(self):
        population = self._population(
            "FULL_PRIMARY_ASSIGNMENTS",
            {
                "and": [
                    {
                        "field": "assignment.assignmentType",
                        "op": "eq",
                        "value": "PRIMARY",
                    },
                    {
                        "field": "assignment.fte",
                        "op": "gte",
                        "value": "1.00",
                    },
                ]
            },
        )
        result = Hr03AssignmentAsOfEvaluationService(77).evaluate_population(
            evidence_no="EV-PRIMARY-FTE-20260801",
            population_code=population.population_code,
            population_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertEqual(result.value, 1)

    def test_assignment_count_metric_uses_frozen_population_version(self):
        population = self._population(
            "CONCURRENT_ASSIGNMENTS",
            {
                "field": "assignment.assignmentType",
                "op": "eq",
                "value": "CONCURRENT",
            },
        )
        metric = MetricDefinitionVersion.objects.create(
            tenant_id=77,
            metric_code="CONCURRENT_ASSIGNMENT_COUNT",
            name="兼岗任职数",
            value_type="INTEGER",
            unit="条",
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
        result = Hr03AssignmentAsOfEvaluationService(77).evaluate_count_metric(
            evidence_no="EV-CONCURRENT-METRIC",
            metric_code=metric.metric_code,
            metric_version=1,
            as_of_date=date(2026, 8, 1),
        )
        self.assertEqual(result.value, 1)
        self.assertEqual(result.definition_kind, "METRIC")
        self.assertEqual(result.grain, "ASSIGNMENT")

    def test_non_assignment_field_and_wrong_grain_fail_closed(self):
        unsupported = self._population(
            "ASSIGNMENT_WITH_CURRENT_FIELD",
            {
                "field": "staff.currentEmploymentStatus",
                "op": "eq",
                "value": "ACTIVE",
            },
        )
        with self.assertRaises(AsOfEvaluationError):
            Hr03AssignmentAsOfEvaluationService(77).evaluate_population(
                evidence_no="EV-ASSIGNMENT-UNSUPPORTED",
                population_code=unsupported.population_code,
                population_version=1,
                as_of_date=date(2026, 8, 1),
            )

        wrong = PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="STAFF_NOT_ASSIGNMENT",
            name="wrong",
            root_domain="HR03",
            grain=PopulationDefinitionVersion.Grain.STAFF,
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03"],
            version_no=1,
            content_hash="a" * 64,
        )
        with self.assertRaises(AsOfEvaluationError) as ctx:
            Hr03AssignmentAsOfEvaluationService(77).evaluate_population(
                evidence_no="EV-WRONG-GRAIN",
                population_code=wrong.population_code,
                population_version=1,
                as_of_date=date(2026, 8, 1),
            )
        self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_GRAIN_UNSUPPORTED")
