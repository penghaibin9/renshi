import uuid
from dataclasses import replace
from datetime import datetime, timezone

from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from hr_assessment.models.result import (
    HrFinalAssessmentResult,
    HrResultApplicationLedger,
)
from hr_assessment.public import (
    AssessmentEvidenceUnavailable,
    FinalAssessmentEvidence,
    record_result_application,
)


class ResultApplicationLedgerTests(TestCase):
    def setUp(self):
        self.result = HrFinalAssessmentResult.objects.create(
            tenant_id=77,
            case_id=uuid.uuid4(),
            assessment_type="ANNUAL",
            grade_code="A",
            display_grade_snapshot_json={"zh-CN": "优秀"},
            finalized_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            result_version_no=1,
            status="FINALIZED",
        )
        self.evidence = FinalAssessmentEvidence(
            result_id=self.result.id,
            case_id=self.result.case_id,
            staff_id=uuid.uuid4(),
            assessment_type="ANNUAL",
            grade_code="A",
            display_grade={"zh-CN": "优秀"},
            calculated_score=None,
            decision_reason="",
            finalized_at=self.result.finalized_at,
            result_version_no=1,
            content_hash=self.result.content_hash,
            policy_version_id=None,
            decision_session_id=None,
            source_result_content_hash=self.result.content_hash,
            calculation_hash=self.result.calculation_hash,
        )

    def test_consumer_replay_is_one_append_only_fact(self):
        object_id = uuid.uuid4()
        first = record_result_application(
            tenant_id=77,
            evidence=self.evidence,
            consumer_domain="HR13",
            consumer_object_id=object_id,
            purpose="PROFESSIONAL_TITLE_MATERIAL",
        )
        replay = record_result_application(
            tenant_id=77,
            evidence=self.evidence,
            consumer_domain="HR13",
            consumer_object_id=object_id,
            purpose="PROFESSIONAL_TITLE_MATERIAL",
        )
        self.assertEqual(first.id, replay.id)
        self.assertEqual(HrResultApplicationLedger.objects.count(), 1)
        with self.assertRaisesRegex(
            ValueError, "HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE"
        ):
            HrResultApplicationLedger.objects.filter(id=first.id).update(
                consumer_status="REVIEWED"
            )

    def test_cross_tenant_result_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "HR12_RESULT_APPLICATION_LEDGER_SCOPE_MISMATCH"
        ):
            HrResultApplicationLedger.objects.create(
                tenant_id=88,
                result=self.result,
                consumer_domain="HR13",
                consumer_object_id=uuid.uuid4(),
                purpose="PROFESSIONAL_TITLE_MATERIAL",
                result_version=1,
            )

        with self.assertRaisesRegex(
            ValueError, "HR12_RESULT_APPLICATION_LEDGER_SCOPE_MISMATCH"
        ):
            HrResultApplicationLedger.objects.bulk_create(
                [
                    HrResultApplicationLedger(
                        tenant_id=88,
                        result=self.result,
                        consumer_domain="HR13",
                        consumer_object_id=uuid.uuid4(),
                        purpose="PROFESSIONAL_TITLE_MATERIAL",
                        result_version=1,
                    )
                ]
            )

    def test_consumer_cannot_record_forged_evidence_fields(self):
        with self.assertRaises(AssessmentEvidenceUnavailable) as error:
            record_result_application(
                tenant_id=77,
                evidence=replace(self.evidence, grade_code="FORGED"),
                consumer_domain="HR13",
                consumer_object_id=uuid.uuid4(),
                purpose="PROFESSIONAL_TITLE_MATERIAL",
            )
        self.assertEqual(
            error.exception.code,
            "ASSESSMENT_RESULT_APPLICATION_VERSION_MISMATCH",
        )

    def test_mysql_trigger_blocks_raw_ledger_update(self):
        if connection.vendor != "mysql":
            self.skipTest("MySQL trigger assertion")
        ledger = record_result_application(
            tenant_id=77,
            evidence=self.evidence,
            consumer_domain="HR13",
            consumer_object_id=uuid.uuid4(),
            purpose="PROFESSIONAL_TITLE_MATERIAL",
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE hr_assessment_result_application_ledger "
                    "SET consumer_status = %s WHERE id = %s",
                    ["REVIEWED", ledger.id.hex],
                )
