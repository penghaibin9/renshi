from django.test import TestCase

from hr_data.models import DimensionDefinitionVersion, PopulationDefinitionVersion
from hr_data.services.definition_service import (
    HrDataDefinitionError,
    HrDataDefinitionService,
)


class Hr18DefinitionServiceTests(TestCase):
    def test_population_definition_is_declarative_versioned_and_idempotent(self):
        service = HrDataDefinitionService(7, actor_user_id=88)
        kwargs = {
            "population_code": "ACTIVE_STAFF",
            "name": "在职教职工",
            "root_domain": "HR03",
            "predicate": {
                "and": [
                    {"field": "employment.status", "op": "eq", "value": "ACTIVE"},
                    {"field": "employment.end_date", "op": "is_null", "value": True},
                ]
            },
            "source_domains": ["HR03"],
        }

        first = service.create_population_version(**kwargs)
        replay = service.create_population_version(**kwargs)

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(replay.definition.id, first.definition.id)
        self.assertEqual(first.definition.version_no, 1)
        self.assertEqual(first.definition.status, "DRAFT")
        self.assertEqual(
            PopulationDefinitionVersion.objects.filter(
                tenant_id=7, population_code="ACTIVE_STAFF"
            ).count(),
            1,
        )

    def test_changed_population_content_appends_next_version(self):
        service = HrDataDefinitionService(7)
        first = service.create_population_version(
            population_code="ACTIVE_STAFF",
            name="在职教职工",
            root_domain="HR03",
            predicate={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
            source_domains=["HR03"],
        )
        second = service.create_population_version(
            population_code="ACTIVE_STAFF",
            name="在职教职工（含借调）",
            root_domain="HR03",
            predicate={
                "field": "employment.status",
                "op": "in",
                "value": ["ACTIVE", "SECONDMENT"],
            },
            source_domains=["HR03"],
        )
        self.assertEqual(first.definition.version_no, 1)
        self.assertEqual(second.definition.version_no, 2)
        self.assertNotEqual(first.definition.content_hash, second.definition.content_hash)

    def test_population_predicate_rejects_executable_or_unscoped_syntax(self):
        service = HrDataDefinitionService(7)
        with self.assertRaises(HrDataDefinitionError) as ctx:
            service.create_population_version(
                population_code="ACTIVE_STAFF",
                name="在职教职工",
                root_domain="HR03",
                predicate={
                    "field": "employment.status; DROP TABLE staff",
                    "op": "eq",
                    "value": "ACTIVE",
                },
                source_domains=["HR03"],
            )
        self.assertEqual(ctx.exception.code, "HR18_POPULATION_FIELD_INVALID")

    def test_root_domain_must_be_declared_in_source_domains(self):
        with self.assertRaises(HrDataDefinitionError) as ctx:
            HrDataDefinitionService(7).create_population_version(
                population_code="ACTIVE_STAFF",
                name="在职教职工",
                root_domain="HR03",
                predicate={"field": "employment.status", "op": "eq", "value": "ACTIVE"},
                source_domains=["HR02"],
            )
        self.assertEqual(ctx.exception.code, "HR18_ROOT_DOMAIN_NOT_DECLARED")

    def test_dimension_definition_is_versioned_and_validates_attribute_path(self):
        service = HrDataDefinitionService(7)
        outcome = service.create_dimension_version(
            dimension_code="DEPARTMENT",
            name="部门",
            source_domain="HR02",
            attribute_path="organization.department_code",
            value_type="CODE",
            label_map={"D001": "信息工程学院"},
        )
        self.assertTrue(outcome.created)
        self.assertEqual(outcome.definition.version_no, 1)
        self.assertEqual(outcome.definition.source_domain, "HR02")
        self.assertEqual(
            DimensionDefinitionVersion.objects.filter(
                tenant_id=7, dimension_code="DEPARTMENT"
            ).count(),
            1,
        )

        with self.assertRaises(HrDataDefinitionError) as ctx:
            service.create_dimension_version(
                dimension_code="BAD_PATH",
                name="非法维度",
                source_domain="HR03",
                attribute_path="staff.__class__.__mro__",
                value_type="STRING",
            )
        self.assertEqual(ctx.exception.code, "HR18_DIMENSION_PATH_INVALID")

    def test_identical_codes_are_isolated_by_tenant(self):
        one = HrDataDefinitionService(7).create_dimension_version(
            dimension_code="GENDER",
            name="性别",
            source_domain="HR03",
            attribute_path="person.gender",
            value_type="CODE",
        )
        two = HrDataDefinitionService(8).create_dimension_version(
            dimension_code="GENDER",
            name="性别",
            source_domain="HR03",
            attribute_path="person.gender",
            value_type="CODE",
        )
        self.assertNotEqual(one.definition.id, two.definition.id)
        self.assertEqual(DimensionDefinitionVersion.objects.count(), 2)
