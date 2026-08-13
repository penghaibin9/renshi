import uuid
from datetime import date

from django.test import TestCase, override_settings

from hr_data.models import DataQualityFinding, DataQualityRuleVersion, DataQualityRun
from hr_data.services.quality_service import (
    DataQualityError,
    DataQualityExecutionService,
    DataQualityRuleService,
)


QUALITY_CALLS = []


def successful_quality_provider(**kwargs):
    QUALITY_CALLS.append(kwargs)
    return {
        "status": "OK",
        "providerVersion": "hr03-quality-v4",
        "evidenceHash": "a" * 64,
        "findings": [
            {
                "sourceObjectRef": "employment:1001",
                "fingerprint": "b" * 64,
                "severity": "INFO",
                "details": {"field": "endDate", "reason": "missing"},
            }
        ],
    }


def partial_quality_provider(**kwargs):
    QUALITY_CALLS.append(kwargs)
    return {
        "status": "PARTIAL",
        "providerVersion": "hr03-quality-v3",
        "evidenceHash": "c" * 64,
        "findings": [
            {
                "sourceObjectRef": "employment:2001",
                "fingerprint": "d" * 64,
                "details": {"reason": "partial source coverage"},
            }
        ],
    }


def failing_quality_provider(**_kwargs):
    raise RuntimeError("quality provider unavailable")


def invalid_quality_provider(**_kwargs):
    return {"status": "OK", "providerVersion": "v1", "findings": []}


class DataQualityRuleServiceTests(TestCase):
    def test_rule_content_is_versioned_and_exact_replay_is_idempotent(self):
        service = DataQualityRuleService(77, actor_user_id=9)
        first = service.create_rule_version(
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            name="在职关系结束日期完整性",
            source_domain="HR03",
            severity="ERROR",
            parameters={"employmentStatuses": ["ACTIVE"]},
            as_of_required=True,
        )
        self.assertTrue(first.created)
        self.assertEqual(first.rule.version_no, 1)
        self.assertEqual(len(first.rule.content_hash), 64)

        replay = service.create_rule_version(
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            name="在职关系结束日期完整性",
            source_domain="HR03",
            severity="ERROR",
            parameters={"employmentStatuses": ["ACTIVE"]},
            as_of_required=True,
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.rule.id, first.rule.id)

        changed = service.create_rule_version(
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            name="在职关系结束日期完整性",
            source_domain="HR03",
            severity="CRITICAL",
            parameters={"employmentStatuses": ["ACTIVE"]},
            as_of_required=True,
        )
        self.assertTrue(changed.created)
        self.assertEqual(changed.rule.version_no, 2)

    def test_rule_definition_rejects_invalid_domain_severity_and_parameters(self):
        service = DataQualityRuleService(77)
        for kwargs, code in (
            (
                {
                    "rule_code": "bad-code",
                    "name": "bad",
                    "source_domain": "HR03",
                    "severity": "ERROR",
                },
                "QUALITY_RULE_CODE_INVALID",
            ),
            (
                {
                    "rule_code": "GOOD_RULE",
                    "name": "bad",
                    "source_domain": "PAYROLL",
                    "severity": "ERROR",
                },
                "QUALITY_SOURCE_DOMAIN_INVALID",
            ),
            (
                {
                    "rule_code": "GOOD_RULE",
                    "name": "bad",
                    "source_domain": "HR03",
                    "severity": "BLOCKER",
                },
                "QUALITY_SEVERITY_INVALID",
            ),
            (
                {
                    "rule_code": "GOOD_RULE",
                    "name": "bad",
                    "source_domain": "HR03",
                    "severity": "ERROR",
                    "parameters": ["not", "an", "object"],
                },
                "QUALITY_RULE_PARAMETERS_INVALID",
            ),
        ):
            with self.assertRaises(DataQualityError) as ctx:
                service.create_rule_version(**kwargs)
            self.assertEqual(ctx.exception.code, code)
        self.assertFalse(DataQualityRuleVersion.objects.filter(tenant_id=77).exists())


class DataQualityExecutionServiceTests(TestCase):
    def setUp(self):
        QUALITY_CALLS.clear()

    def _rule(
        self,
        *,
        tenant_id=77,
        code="EMPLOYMENT_END_DATE_REQUIRED",
        severity="CRITICAL",
        as_of_required=False,
        content_hash="e" * 64,
    ):
        return DataQualityRuleVersion.objects.create(
            tenant_id=tenant_id,
            rule_code=code,
            name="在职关系结束日期完整性",
            source_domain="HR03",
            severity=severity,
            parameters_json={"statuses": ["ACTIVE"]},
            as_of_required=as_of_required,
            version_no=1,
            content_hash=content_hash,
        )

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_service.successful_quality_provider"
        }
    )
    def test_successful_provider_creates_durable_run_and_rule_owned_findings(self):
        rule = self._rule()
        outcome = DataQualityExecutionService(77, actor_user_id=9).execute(
            run_no="QRUN-001",
            rule_code=rule.rule_code,
            rule_version=1,
        )

        self.assertTrue(outcome.created)
        self.assertEqual(outcome.run.status, DataQualityRun.Status.SUCCESS)
        self.assertEqual(outcome.run.provider_version, "hr03-quality-v4")
        self.assertEqual(outcome.run.evidence_hash, "a" * 64)
        self.assertEqual(outcome.run.finding_count, 1)
        self.assertEqual(len(outcome.findings), 1)
        finding = outcome.findings[0]
        self.assertEqual(finding.severity, DataQualityFinding.Severity.CRITICAL)
        self.assertEqual(finding.finding_fingerprint, "b" * 64)
        self.assertEqual(finding.details_json["field"], "endDate")
        self.assertEqual(finding.quality_run_id, outcome.run.id)
        self.assertEqual(len(QUALITY_CALLS), 1)
        self.assertEqual(QUALITY_CALLS[0]["tenant_id"], 77)
        self.assertEqual(QUALITY_CALLS[0]["rule_parameters"], {"statuses": ["ACTIVE"]})

        replay = DataQualityExecutionService(77, actor_user_id=99).execute(
            run_no="QRUN-001",
            rule_code=rule.rule_code,
            rule_version=1,
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.run.id, outcome.run.id)
        self.assertEqual(len(replay.findings), 1)
        self.assertEqual(len(QUALITY_CALLS), 1)

        outcome.run.finding_count = 99
        with self.assertRaisesRegex(ValueError, "HR18_DATA_QUALITY_RUN_IMMUTABLE"):
            outcome.run.save()
        finding.source_object_ref = "employment:changed"
        with self.assertRaisesRegex(
            ValueError, "HR18_DATA_QUALITY_FINDING_IDENTITY_IMMUTABLE"
        ):
            finding.save()

    def test_missing_provider_creates_unavailable_run_without_findings(self):
        rule = self._rule()
        outcome = DataQualityExecutionService(77).execute(
            run_no="QRUN-UNAVAILABLE",
            rule_code=rule.rule_code,
            rule_version=1,
        )
        self.assertEqual(outcome.run.status, DataQualityRun.Status.UNAVAILABLE)
        self.assertEqual(outcome.run.finding_count, 0)
        self.assertEqual(outcome.findings, ())
        self.assertIn("not registered", outcome.run.error_message)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_service.failing_quality_provider"
        }
    )
    def test_provider_exception_is_persisted_as_error_not_fake_success(self):
        rule = self._rule()
        outcome = DataQualityExecutionService(77).execute(
            run_no="QRUN-ERROR",
            rule_code=rule.rule_code,
            rule_version=1,
        )
        self.assertEqual(outcome.run.status, DataQualityRun.Status.ERROR)
        self.assertEqual(outcome.findings, ())
        self.assertIn("quality provider unavailable", outcome.run.error_message)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_service.invalid_quality_provider"
        }
    )
    def test_provider_missing_evidence_hash_becomes_error(self):
        rule = self._rule()
        outcome = DataQualityExecutionService(77).execute(
            run_no="QRUN-BAD-CONTRACT",
            rule_code=rule.rule_code,
            rule_version=1,
        )
        self.assertEqual(outcome.run.status, DataQualityRun.Status.ERROR)
        self.assertEqual(outcome.run.finding_count, 0)
        self.assertIn("evidence contract", outcome.run.error_message)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_service.partial_quality_provider"
        }
    )
    def test_partial_provider_keeps_findings_but_run_is_not_success(self):
        rule = self._rule(severity="WARNING")
        outcome = DataQualityExecutionService(77).execute(
            run_no="QRUN-PARTIAL",
            rule_code=rule.rule_code,
            rule_version=1,
        )
        self.assertEqual(outcome.run.status, DataQualityRun.Status.PARTIAL)
        self.assertEqual(outcome.run.finding_count, 1)
        self.assertEqual(outcome.findings[0].severity, DataQualityFinding.Severity.WARNING)

    def test_asof_required_cross_tenant_and_changed_run_identity_fail_closed(self):
        rule = self._rule(as_of_required=True)
        with self.assertRaises(DataQualityError) as ctx:
            DataQualityExecutionService(77).execute(
                run_no="QRUN-ASOF",
                rule_code=rule.rule_code,
                rule_version=1,
            )
        self.assertEqual(ctx.exception.code, "QUALITY_ASOF_DATE_REQUIRED")
        self.assertFalse(DataQualityRun.objects.filter(run_no="QRUN-ASOF").exists())

        self._rule(tenant_id=88, code="FOREIGN_RULE")
        with self.assertRaises(DataQualityError) as ctx:
            DataQualityExecutionService(77).execute(
                run_no="QRUN-XTENANT",
                rule_code="FOREIGN_RULE",
                rule_version=1,
            )
        self.assertEqual(ctx.exception.code, "QUALITY_RULE_NOT_FOUND")

        first = DataQualityRun.objects.create(
            tenant_id=77,
            run_no="QRUN-CONFLICT",
            rule_code=rule.rule_code,
            rule_version=1,
            source_domain="HR03",
            as_of_date=date(2026, 8, 1),
            status=DataQualityRun.Status.UNAVAILABLE,
        )
        self.assertIsNotNone(first.id)
        with self.assertRaises(DataQualityError) as ctx:
            DataQualityExecutionService(77).execute(
                run_no="QRUN-CONFLICT",
                rule_code=rule.rule_code,
                rule_version=1,
                as_of_date=date(2026, 8, 2),
            )
        self.assertEqual(ctx.exception.code, "QUALITY_RUN_IDEMPOTENCY_CONFLICT")

    def test_rule_without_frozen_hash_cannot_execute(self):
        rule = self._rule(content_hash="")
        with self.assertRaises(DataQualityError) as ctx:
            DataQualityExecutionService(77).execute(
                run_no="QRUN-NOHASH",
                rule_code=rule.rule_code,
                rule_version=1,
            )
        self.assertEqual(ctx.exception.code, "QUALITY_RULE_HASH_INVALID")
        self.assertFalse(DataQualityRun.objects.filter(run_no="QRUN-NOHASH").exists())
