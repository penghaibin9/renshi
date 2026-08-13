from datetime import date

from django.test import TestCase

from hr_data.models import DataQualityRuleVersion, DataQualityRun, SubmissionSnapshot
from hr_data.selectors import dashboard_snapshot


class Hr18SelectorCapabilityTests(TestCase):
    def test_dashboard_reports_real_receipt_capability(self):
        SubmissionSnapshot.objects.create(
            tenant_id=77,
            submission_no="SUB-001",
            definition_code="EDU-HR",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            payload_hash="a" * 64,
            status=SubmissionSnapshot.Status.ACCEPTED,
            receipt_ref="receipt-001",
        )
        SubmissionSnapshot.objects.create(
            tenant_id=77,
            submission_no="SUB-002",
            definition_code="EDU-HR",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            payload_hash="b" * 64,
            status=SubmissionSnapshot.Status.SUBMITTED,
        )

        payload = dashboard_snapshot(77)

        self.assertTrue(payload["capabilities"]["submissionReceipt"])
        self.assertEqual(payload["summary"]["acceptedReceipts"], 1)
        self.assertEqual(payload["summary"]["awaitingReceipt"], 1)

    def test_receipt_counts_are_tenant_scoped(self):
        common = {
            "definition_code": "EDU-HR",
            "definition_version": 1,
            "as_of_date": date(2026, 8, 1),
            "status": SubmissionSnapshot.Status.REJECTED,
            "receipt_ref": "rejected-receipt",
        }
        SubmissionSnapshot.objects.create(
            tenant_id=77,
            submission_no="SUB-77",
            payload_hash="c" * 64,
            **common,
        )
        SubmissionSnapshot.objects.create(
            tenant_id=88,
            submission_no="SUB-88",
            payload_hash="d" * 64,
            **common,
        )

        payload = dashboard_snapshot(77)

        self.assertEqual(payload["summary"]["submissions"], 1)
        self.assertEqual(payload["summary"]["rejectedReceipts"], 1)
        self.assertEqual([row["submission_no"] for row in payload["recentSubmissions"]], ["SUB-77"])

    def test_dashboard_reports_real_quality_execution_capability_and_run_health(self):
        DataQualityRuleVersion.objects.create(
            tenant_id=77,
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            name="结束日期完整性",
            source_domain="HR03",
            severity="ERROR",
            version_no=1,
            content_hash="e" * 64,
        )
        DataQualityRun.objects.create(
            tenant_id=77,
            run_no="QRUN-UNAVAILABLE",
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            rule_version=1,
            source_domain="HR03",
            status=DataQualityRun.Status.UNAVAILABLE,
        )
        DataQualityRun.objects.create(
            tenant_id=88,
            run_no="QRUN-OTHER-TENANT",
            rule_code="EMPLOYMENT_END_DATE_REQUIRED",
            rule_version=1,
            source_domain="HR03",
            status=DataQualityRun.Status.ERROR,
        )

        payload = dashboard_snapshot(77)

        self.assertTrue(payload["capabilities"]["qualityRuleExecution"])
        self.assertEqual(payload["summary"]["qualityRuleVersions"], 1)
        self.assertEqual(payload["summary"]["qualityRuns"], 1)
        self.assertEqual(payload["summary"]["qualityUnavailableRuns"], 1)
        self.assertEqual(payload["summary"]["qualityErrorRuns"], 0)
        self.assertEqual(payload["recentQualityRuns"][0]["run_no"], "QRUN-UNAVAILABLE")
