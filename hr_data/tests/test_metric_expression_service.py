import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from hr_data.models import (
    AsOfEvidenceSnapshot,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    MetricEvaluationSnapshot,
    PopulationDefinitionVersion,
)
from hr_data.services.metric_expression_service import (
    MetricExpressionError,
    MetricExpressionEvaluationService,
)


class MetricAggregateDslTests(SimpleTestCase):
    def test_all_whitelisted_aggregate_operators_use_exact_arithmetic(self):
        records = [
            {"payroll.grossamount": "10.25"},
            {"payroll.grossamount": "20.75"},
            {"payroll.grossamount": None},
        ]
        expectations = {
            "SUM": "31",
            "AVG": "15.5",
            "MIN": "10.25",
            "MAX": "20.75",
        }
        for op, expected in expectations.items():
            with self.subTest(op=op):
                self.assertEqual(
                    MetricExpressionEvaluationService._aggregate(
                        records,
                        expression={"op": op, "field": "payroll.grossAmount"},
                        value_type="DECIMAL",
                    ),
                    expected,
                )
        self.assertEqual(
            MetricExpressionEvaluationService._aggregate(
                records,
                expression={"op": "COUNT", "field": None},
                value_type="INTEGER",
            ),
            3,
        )

    def test_float_and_missing_provider_fields_fail_closed(self):
        with self.assertRaises(MetricExpressionError) as ctx:
            MetricExpressionEvaluationService._number(0.1)
        self.assertEqual(ctx.exception.code, "HR18_METRIC_VALUE_TYPE_INVALID")
        with self.assertRaises(MetricExpressionError) as ctx:
            MetricExpressionEvaluationService._aggregate(
                [{}],
                expression={"op": "SUM", "field": "payroll.grossAmount"},
                value_type="DECIMAL",
            )
        self.assertEqual(ctx.exception.code, "HR18_METRIC_FIELD_NOT_PROVIDED")


def fake_provider(**kwargs):
    requested = set(kwargs["requested_fields"])
    records = [
        {
            "employment.staffId": "staff-1",
            "employment.status": "ACTIVE",
        },
        {
            "employment.staffId": "staff-1",
            "employment.status": "ACTIVE",
        },
        {
            "employment.staffId": "staff-2",
            "employment.status": "LEAVE",
        },
    ]
    return {
        "status": "OK",
        "providerVersion": "test-row-provider-v1",
        "sourceReceipts": {
            "HR03": {
                "status": "OK",
                "sourceVersion": "hr03-source-v1",
                "evidenceHash": "c" * 64,
            }
        },
        "records": [
            {key: value for key, value in row.items() if key in requested}
            for row in records
        ],
    }


def stale_provider(**kwargs):
    payload = fake_provider(**kwargs)
    payload["sourceReceipts"]["HR03"]["evidenceHash"] = "d" * 64
    return payload


@override_settings(
    HR18_METRIC_DATA_PROVIDERS={
        "HR03": "hr_data.tests.test_metric_expression_service.fake_provider"
    }
)
class MetricExpressionEvaluationServiceTests(TestCase):
    def setUp(self):
        self.population = PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code="STAFF_RELATIONSHIPS",
            name="教职工关系",
            root_domain="HR03",
            grain=PopulationDefinitionVersion.Grain.EMPLOYMENT_RELATIONSHIP,
            predicate_json={
                "field": "employment.status",
                "op": "in",
                "value": ["ACTIVE", "LEAVE"],
            },
            source_domains=["HR03"],
            version_no=2,
            content_hash="a" * 64,
        )
        self.dimension = DimensionDefinitionVersion.objects.create(
            tenant_id=77,
            dimension_code="EMPLOYMENT_STATUS",
            name="在职状态",
            source_domain="HR03",
            attribute_path="employment.status",
            value_type="CODE",
            label_map_json={"ACTIVE": "在职", "LEAVE": "休假"},
            version_no=3,
            content_hash="b" * 64,
        )
        self.metric = MetricDefinitionVersion.objects.create(
            tenant_id=77,
            metric_code="DISTINCT_STAFF",
            name="教职工人数",
            value_type="INTEGER",
            population_code=self.population.population_code,
            expression=json.dumps(
                {
                    "dslVersion": "1",
                    "populationVersion": 2,
                    "op": "COUNT_DISTINCT",
                    "field": "employment.staffId",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            source_domains=["HR03"],
            version_no=4,
            content_hash="e" * 64,
        )
        self.evidence = AsOfEvidenceSnapshot.objects.create(
            tenant_id=77,
            evidence_no="METRIC-EVID-1",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=self.metric.metric_code,
            definition_version=self.metric.version_no,
            as_of_date=date(2026, 8, 1),
            status=AsOfEvidenceSnapshot.Status.COMPLETE,
            source_statuses_json={"HR03": "OK"},
            blocked_domains_json=[],
            provider_versions_json={"HR03": "hr03-source-v1"},
            provider_evidence_hashes_json={"HR03": "c" * 64},
            evidence_hash="f" * 64,
        )

    def _evaluate(self, **overrides):
        params = {
            "evaluation_no": "EVAL-001",
            "metric_code": self.metric.metric_code,
            "metric_version": self.metric.version_no,
            "as_of_date": date(2026, 8, 1),
            "evidence_id": self.evidence.id,
            "dimensions": [{"code": self.dimension.dimension_code, "version": 3}],
        }
        params.update(overrides)
        return MetricExpressionEvaluationService(77, actor_user_id=9).evaluate(**params)

    def test_grouped_distinct_metric_creates_immutable_audit_snapshot(self):
        outcome = self._evaluate()

        self.assertTrue(outcome.created)
        snapshot = outcome.snapshot
        self.assertEqual(snapshot.created_by, 9)
        self.assertEqual(snapshot.input_row_count, 3)
        self.assertEqual(snapshot.provider_version, "test-row-provider-v1")
        self.assertEqual(len(snapshot.calculation_hash), 64)
        self.assertEqual(
            snapshot.dimension_versions_json,
            [{"code": "EMPLOYMENT_STATUS", "version": 3}],
        )
        self.assertEqual(
            snapshot.result_json["groups"],
            [
                {
                    "dimensions": {"EMPLOYMENT_STATUS": "ACTIVE"},
                    "labels": {"EMPLOYMENT_STATUS": "在职"},
                    "value": 1,
                },
                {
                    "dimensions": {"EMPLOYMENT_STATUS": "LEAVE"},
                    "labels": {"EMPLOYMENT_STATUS": "休假"},
                    "value": 1,
                },
            ],
        )
        snapshot.result_json = {"kind": "SCALAR", "value": 999}
        with self.assertRaisesRegex(ValueError, "HR18_METRIC_EVALUATION_IMMUTABLE"):
            snapshot.save()

    def test_replay_is_idempotent_but_identity_reuse_conflicts(self):
        first = self._evaluate()
        replay = self._evaluate()

        self.assertFalse(replay.created)
        self.assertEqual(replay.snapshot.id, first.snapshot.id)
        with self.assertRaises(MetricExpressionError) as ctx:
            self._evaluate(dimensions=[])
        self.assertEqual(ctx.exception.code, "HR18_METRIC_EVALUATION_IDEMPOTENCY_CONFLICT")
        self.assertEqual(MetricEvaluationSnapshot.objects.filter(tenant_id=77).count(), 1)

    def test_cross_tenant_and_incomplete_evidence_fail_closed(self):
        foreign = AsOfEvidenceSnapshot.objects.create(
            tenant_id=88,
            evidence_no="FOREIGN",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code=self.metric.metric_code,
            definition_version=4,
            as_of_date=date(2026, 8, 1),
            status=AsOfEvidenceSnapshot.Status.COMPLETE,
            source_statuses_json={"HR03": "OK"},
            provider_versions_json={"HR03": "hr03-source-v1"},
            provider_evidence_hashes_json={"HR03": "c" * 64},
            evidence_hash="9" * 64,
        )
        with self.assertRaises(MetricExpressionError) as ctx:
            self._evaluate(evidence_id=foreign.id)
        self.assertEqual(ctx.exception.code, "HR18_METRIC_EVIDENCE_NOT_FOUND")

        self.evidence.status = AsOfEvidenceSnapshot.Status.PARTIAL
        AsOfEvidenceSnapshot.objects.filter(id=self.evidence.id).update(status="PARTIAL")
        with patch(
            "hr_data.services.metric_expression_service.import_string"
        ) as provider_loader:
            with self.assertRaises(MetricExpressionError) as ctx:
                self._evaluate(evaluation_no="EVAL-INCOMPLETE")
        self.assertEqual(ctx.exception.code, "HR18_METRIC_EVIDENCE_INCOMPLETE")
        provider_loader.assert_not_called()

    @override_settings(
        HR18_METRIC_DATA_PROVIDERS={
            "HR03": "hr_data.tests.test_metric_expression_service.stale_provider"
        }
    )
    def test_current_provider_receipt_must_match_frozen_evidence(self):
        with self.assertRaises(MetricExpressionError) as ctx:
            self._evaluate(evaluation_no="EVAL-STALE")
        self.assertEqual(ctx.exception.code, "HR18_METRIC_EVIDENCE_STALE")
        self.assertFalse(MetricEvaluationSnapshot.objects.exists())

    def test_noncanonical_or_executable_expression_never_reaches_provider(self):
        self.metric.expression = json.dumps(
            {
                "dslVersion": "1",
                "populationVersion": 2,
                "op": "COUNT",
                "field": None,
                "sql": "SELECT * FROM hr_staff",
            }
        )
        MetricDefinitionVersion.objects.filter(id=self.metric.id).update(
            expression=self.metric.expression
        )
        with patch(
            "hr_data.services.metric_expression_service.import_string"
        ) as provider_loader:
            with self.assertRaises(MetricExpressionError) as ctx:
                self._evaluate(evaluation_no="EVAL-BAD-DSL")
        self.assertEqual(ctx.exception.code, "HR18_METRIC_EXPRESSION_INVALID")
        provider_loader.assert_not_called()
