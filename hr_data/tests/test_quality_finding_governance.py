import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from hr_data import quality_finding_api
from hr_data.models import DataQualityFinding, DataQualityRuleVersion, DataQualityRun
from hr_data.services.quality_finding_service import (
    DataQualityFindingError,
    DataQualityFindingService,
    FindingVerificationResult,
)


VERIFY_CALLS = []


def fixed_provider(**kwargs):
    VERIFY_CALLS.append(kwargs)
    return {
        "status": "OK",
        "providerVersion": "hr03-quality-fixed-v1",
        "evidenceHash": "a" * 64,
        "findings": [],
    }


def still_present_provider(**kwargs):
    VERIFY_CALLS.append(kwargs)
    return {
        "status": "OK",
        "providerVersion": "hr03-quality-still-v1",
        "evidenceHash": "c" * 64,
        "findings": [
            {
                "sourceObjectRef": "employment:1001",
                "fingerprint": "b" * 64,
                "details": {"reason": "still missing"},
            }
        ],
    }


def partial_provider(**kwargs):
    VERIFY_CALLS.append(kwargs)
    return {
        "status": "PARTIAL",
        "providerVersion": "hr03-quality-partial-v1",
        "evidenceHash": "d" * 64,
        "findings": [],
    }


class DataQualityFindingServiceTests(TestCase):
    def setUp(self):
        VERIFY_CALLS.clear()
        self.rule = DataQualityRuleVersion.objects.create(
            tenant_id=77,
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            name="在职关系结束日期完整性",
            source_domain="HR03",
            severity="ERROR",
            parameters_json={"statuses": ["ACTIVE"]},
            as_of_required=False,
            version_no=1,
            content_hash="e" * 64,
        )
        self.run = DataQualityRun.objects.create(
            tenant_id=77,
            run_no="QRUN-ORIGINAL",
            rule_code=self.rule.rule_code,
            rule_version=1,
            source_domain="HR03",
            status=DataQualityRun.Status.SUCCESS,
            provider_version="hr03-quality-v1",
            evidence_hash="f" * 64,
            finding_count=1,
        )
        self.finding = DataQualityFinding.objects.create(
            tenant_id=77,
            finding_no="DQ-001",
            quality_run_id=self.run.id,
            rule_code=self.rule.rule_code,
            rule_version=1,
            source_domain="HR03",
            source_object_ref="employment:1001",
            finding_fingerprint="b" * 64,
            severity=DataQualityFinding.Severity.ERROR,
            details_json={"field": "endDate"},
            status=DataQualityFinding.Status.OPEN,
            detected_at=timezone.now(),
        )

    def test_acknowledge_is_tenant_bound_and_idempotent(self):
        service = DataQualityFindingService(77, actor_user_id=9)
        finding = service.acknowledge(self.finding.id)
        self.assertEqual(finding.status, DataQualityFinding.Status.ACKNOWLEDGED)
        self.assertEqual(finding.updated_by, 9)

        replay = service.acknowledge(self.finding.id)
        self.assertEqual(replay.status, DataQualityFinding.Status.ACKNOWLEDGED)

        with self.assertRaises(DataQualityFindingError) as ctx:
            DataQualityFindingService(88).acknowledge(self.finding.id)
        self.assertEqual(ctx.exception.code, "QUALITY_FINDING_NOT_FOUND")

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_finding_governance.fixed_provider"
        }
    )
    def test_fixed_at_source_requires_fresh_successful_provider_verification(self):
        outcome = DataQualityFindingService(77, actor_user_id=11).verify_fixed(
            self.finding.id,
            verification_run_no="QRUN-VERIFY-001",
        )

        self.assertTrue(outcome.changed)
        self.assertEqual(outcome.verification_run.status, DataQualityRun.Status.SUCCESS)
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, DataQualityFinding.Status.FIXED_AT_SOURCE)
        self.assertIsNotNone(self.finding.resolved_at)
        self.assertEqual(self.finding.updated_by, 11)
        self.assertEqual(len(VERIFY_CALLS), 1)

        replay = DataQualityFindingService(77).verify_fixed(
            self.finding.id,
            verification_run_no="QRUN-VERIFY-REPLAY",
        )
        self.assertFalse(replay.changed)
        self.assertIsNone(replay.verification_run)
        self.assertEqual(len(VERIFY_CALLS), 1)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_finding_governance.still_present_provider"
        }
    )
    def test_same_fingerprint_still_present_cannot_be_marked_fixed(self):
        with self.assertRaises(DataQualityFindingError) as ctx:
            DataQualityFindingService(77).verify_fixed(
                self.finding.id,
                verification_run_no="QRUN-VERIFY-STILL",
            )
        self.assertEqual(ctx.exception.code, "QUALITY_FINDING_STILL_PRESENT")
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, DataQualityFinding.Status.OPEN)
        self.assertIsNone(self.finding.resolved_at)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_finding_governance.partial_provider"
        }
    )
    def test_partial_or_unavailable_verification_cannot_prove_fix(self):
        with self.assertRaises(DataQualityFindingError) as ctx:
            DataQualityFindingService(77).verify_fixed(
                self.finding.id,
                verification_run_no="QRUN-VERIFY-PARTIAL",
            )
        self.assertEqual(ctx.exception.code, "QUALITY_FIX_VERIFICATION_INCOMPLETE")
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status, DataQualityFinding.Status.OPEN)

    @override_settings(
        HR18_QUALITY_PROVIDERS={
            "HR03": "hr_data.tests.test_quality_finding_governance.fixed_provider"
        }
    )
    def test_historical_finding_cannot_be_rewritten_by_current_repair(self):
        DataQualityRun.objects.filter(id=self.run.id).update(as_of_date=date(2026, 8, 1))
        with self.assertRaises(DataQualityFindingError) as ctx:
            DataQualityFindingService(77).verify_fixed(
                self.finding.id,
                verification_run_no="QRUN-VERIFY-HISTORY",
            )
        self.assertEqual(ctx.exception.code, "QUALITY_HISTORICAL_FINDING_IMMUTABLE")
        self.assertEqual(VERIFY_CALLS, [])

    def test_verification_cannot_reuse_original_run_identity(self):
        with self.assertRaises(DataQualityFindingError) as ctx:
            DataQualityFindingService(77).verify_fixed(
                self.finding.id,
                verification_run_no=self.run.run_no,
            )
        self.assertEqual(ctx.exception.code, "QUALITY_VERIFICATION_RUN_REUSE_FORBIDDEN")


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class DataQualityFindingApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.finding_id = uuid.uuid4()
        self.now = timezone.now()

    def _finding(self, status="ACKNOWLEDGED"):
        return SimpleNamespace(
            id=self.finding_id,
            finding_no="DQ-001",
            quality_run_id=uuid.uuid4(),
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            rule_version=1,
            source_domain="HR03",
            source_object_ref="employment:1001",
            finding_fingerprint="b" * 64,
            severity="ERROR",
            details_json={"field": "endDate"},
            status=status,
            detected_at=self.now,
            resolved_at=self.now if status == "FIXED_AT_SOURCE" else None,
        )

    @patch("hr_data.quality_finding_api.DataQualityFindingService")
    @patch("hr_data.quality_finding_api.resolve_request_tenant", return_value=77)
    def test_acknowledge_requires_quality_permission_and_calls_authority(
        self, tenant_resolver, service_cls
    ):
        service_cls.return_value.acknowledge.return_value = self._finding()
        request = self.factory.post("/ack")
        request.user = UserStub()

        response = quality_finding_api.acknowledge(request, self.finding_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request,
            required_permission=quality_finding_api.QUALITY_PERMISSION,
        )
        service_cls.return_value.acknowledge.assert_called_once_with(self.finding_id)
        self.assertEqual(response["Cache-Control"], "no-store")

    @patch("hr_data.quality_finding_api.DataQualityFindingService")
    @patch("hr_data.quality_finding_api.resolve_request_tenant", return_value=77)
    def test_verify_fixed_requires_explicit_new_verification_run_no(
        self, _tenant, service_cls
    ):
        verification = SimpleNamespace(id=uuid.uuid4(), run_no="QRUN-VERIFY-9")
        service_cls.return_value.verify_fixed.return_value = FindingVerificationResult(
            self._finding(status="FIXED_AT_SOURCE"),
            verification,
            True,
        )
        request = self.factory.post(
            "/verify-fixed",
            data=json.dumps({"verificationRunNo": "QRUN-VERIFY-9"}),
            content_type="application/json",
        )
        request.user = UserStub()

        response = quality_finding_api.verify_fixed(request, self.finding_id)

        self.assertEqual(response.status_code, 200)
        service_cls.return_value.verify_fixed.assert_called_once_with(
            self.finding_id,
            verification_run_no="QRUN-VERIFY-9",
        )
        self.assertIn(b"QRUN-VERIFY-9", response.content)

    @patch("hr_data.quality_finding_api.DataQualityFindingService")
    @patch("hr_data.quality_finding_api.resolve_request_tenant", return_value=77)
    def test_still_present_maps_to_conflict(self, _tenant, service_cls):
        service_cls.return_value.verify_fixed.side_effect = DataQualityFindingError(
            "QUALITY_FINDING_STILL_PRESENT",
            "still present",
        )
        request = self.factory.post(
            "/verify-fixed",
            data=json.dumps({"verificationRunNo": "QRUN-VERIFY-10"}),
            content_type="application/json",
        )
        request.user = UserStub()

        response = quality_finding_api.verify_fixed(request, self.finding_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"QUALITY_FINDING_STILL_PRESENT", response.content)
