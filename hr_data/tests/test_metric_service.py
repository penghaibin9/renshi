import json

from django.test import TestCase

from hr_data.models import MetricDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.definition_service import HrDataDefinitionError
from hr_data.services.metric_service import HrMetricDefinitionService


class HrMetricDefinitionServiceTests(TestCase):
    def test_count_metric_is_canonical_and_freezes_population_version(self):
        population = PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="ACTIVE_STAFF",
            name="在职教职工",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03"],
            as_of_required=True,
            version_no=1,
            content_hash="a" * 64,
        )
        service = HrMetricDefinitionService(77, actor_user_id=9)

        outcome = service.create_metric_version(
            metric_code="ACTIVE_STAFF_COUNT",
            name="在职教职工人数",
            value_type="INTEGER",
            population_code=population.population_code,
            population_version=population.version_no,
            expression={"op": "COUNT"},
            source_domains=["HR03"],
            unit="人",
        )

        self.assertTrue(outcome.created)
        definition = outcome.definition
        document = json.loads(definition.expression)
        self.assertEqual(document["dslVersion"], "1")
        self.assertEqual(document["populationVersion"], 1)
        self.assertEqual(document["op"], "COUNT")
        self.assertIsNone(document["field"])
        self.assertEqual(definition.population_code, "ACTIVE_STAFF")
        self.assertEqual(definition.source_domains, ["HR03"])
        self.assertEqual(len(definition.content_hash), 64)

        replay = service.create_metric_version(
            metric_code="ACTIVE_STAFF_COUNT",
            name="在职教职工人数",
            value_type="INTEGER",
            population_code="ACTIVE_STAFF",
            population_version=1,
            expression={"op": "COUNT"},
            source_domains=["HR03"],
            unit="人",
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.definition.id, definition.id)

    def test_changed_metric_content_creates_next_version(self):
        PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="ACTIVE_STAFF",
            name="在职教职工",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03"],
            version_no=1,
            content_hash="a" * 64,
        )
        service = HrMetricDefinitionService(77)
        first = service.create_metric_version(
            metric_code="HEADCOUNT",
            name="人数",
            value_type="INTEGER",
            population_code="ACTIVE_STAFF",
            population_version=1,
            expression={"op": "COUNT"},
            source_domains=["HR03"],
        ).definition
        second = service.create_metric_version(
            metric_code="HEADCOUNT",
            name="人数（人）",
            value_type="INTEGER",
            population_code="ACTIVE_STAFF",
            population_version=1,
            expression={"op": "COUNT"},
            source_domains=["HR03"],
        ).definition
        self.assertEqual(first.version_no, 1)
        self.assertEqual(second.version_no, 2)

    def test_arbitrary_or_unsupported_expression_is_rejected(self):
        PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="ACTIVE_STAFF",
            name="在职教职工",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03"],
            version_no=1,
            content_hash="a" * 64,
        )
        service = HrMetricDefinitionService(77)
        for expression in (
            "SELECT COUNT(*) FROM employee",
            {"op": "PYTHON", "field": "__import__.os"},
            {"op": "COUNT", "field": "staff.id", "sql": "DROP TABLE x"},
        ):
            with self.assertRaises(HrDataDefinitionError):
                service.create_metric_version(
                    metric_code="BAD_METRIC",
                    name="坏指标",
                    value_type="INTEGER",
                    population_code="ACTIVE_STAFF",
                    population_version=1,
                    expression=expression,
                    source_domains=["HR03"],
                )
        self.assertFalse(MetricDefinitionVersion.objects.filter(tenant_id=77).exists())

    def test_cross_tenant_population_and_missing_sources_fail_closed(self):
        PopulationDefinitionVersion.objects.create(
            tenant_id=88,
            population_code="ACTIVE_STAFF",
            name="外校人口",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03", "HR14"],
            version_no=1,
            content_hash="a" * 64,
        )
        service = HrMetricDefinitionService(77)
        with self.assertRaises(HrDataDefinitionError) as ctx:
            service.create_metric_version(
                metric_code="HEADCOUNT",
                name="人数",
                value_type="INTEGER",
                population_code="ACTIVE_STAFF",
                population_version=1,
                expression={"op": "COUNT"},
                source_domains=["HR03"],
            )
        self.assertEqual(ctx.exception.code, "HR18_POPULATION_VERSION_NOT_FOUND")

        PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="ACTIVE_STAFF",
            name="本校人口",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03", "HR14"],
            version_no=1,
            content_hash="b" * 64,
        )
        with self.assertRaises(HrDataDefinitionError) as ctx:
            service.create_metric_version(
                metric_code="HEADCOUNT",
                name="人数",
                value_type="INTEGER",
                population_code="ACTIVE_STAFF",
                population_version=1,
                expression={"op": "COUNT"},
                source_domains=["HR03"],
            )
        self.assertEqual(ctx.exception.code, "HR18_METRIC_SOURCE_DOMAINS_INCOMPLETE")

    def test_aggregate_field_path_and_value_type_are_typed(self):
        PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="PAYROLL_POP",
            name="工资人口",
            root_domain="HR03",
            predicate_json={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03", "HR15"],
            version_no=1,
            content_hash="c" * 64,
        )
        service = HrMetricDefinitionService(77)
        outcome = service.create_metric_version(
            metric_code="TOTAL_GROSS_PAY",
            name="应发合计",
            value_type="DECIMAL",
            population_code="PAYROLL_POP",
            population_version=1,
            expression={"op": "SUM", "field": "payroll.grossAmount"},
            source_domains=["HR03", "HR15"],
            unit="CNY",
        )
        self.assertEqual(json.loads(outcome.definition.expression)["op"], "SUM")

        with self.assertRaises(HrDataDefinitionError) as ctx:
            service.create_metric_version(
                metric_code="BAD_COUNT",
                name="错误人数",
                value_type="DECIMAL",
                population_code="PAYROLL_POP",
                population_version=1,
                expression={"op": "COUNT"},
                source_domains=["HR03", "HR15"],
            )
        self.assertEqual(ctx.exception.code, "HR18_METRIC_VALUE_TYPE_MISMATCH")
