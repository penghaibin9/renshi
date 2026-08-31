"""HR12 list public-contract evidence tests."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult, HrResultRevision
from hr_assessment.public import (
    AssessmentEvidenceUnavailable,
    get_finalized_assessment_evidence,
    list_finalized_assessment_evidence,
)
from hr_staff.models import HrPerson, HrStaffMaster


class FinalAssessmentListPublicContractTests(TestCase):
    def setUp(self):
        self.tenant_id = 80123
        self.person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="HR12 public contract",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no=f"HR12-PUBLIC-{uuid.uuid4().hex}",
        )

    def _result(self, *, staff=None, finalized_at=None, status="FINALIZED"):
        staff = staff or self.staff
        case = HrAssessmentCase.objects.create(
            tenant_id=self.tenant_id,
            assessment_type="ANNUAL",
            staff_id=staff.id,
            status="FINALIZED",
        )
        return HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id,
            case_id=case.id,
            assessment_type="ANNUAL",
            grade_code="A",
            display_grade_snapshot_json={"zh-CN": "优秀"},
            calculated_score=Decimal("91.00"),
            decision_reason="formal",
            finalized_at=finalized_at
            or datetime(2026, 6, 30, 8, 0, tzinfo=timezone.utc),
            result_version_no=1,
            status=status,
        )

    def _revision(self, result, *, revision_type="CORRECTION", effective_at=None):
        before = {
            "sourceResultId": str(result.id),
            "sourceContentHash": result.content_hash,
            "version": 1,
            "status": "FINALIZED",
            "gradeCode": "A",
            "displayGrade": {"zh-CN": "优秀"},
            "calculatedScore": "91.00",
            "decisionReason": "formal",
        }
        after = dict(before)
        after["version"] = 2
        if revision_type == "REVOCATION":
            after["status"] = "REVOKED"
        else:
            after.update(
                {
                    "status": "CORRECTED",
                    "gradeCode": "B",
                    "displayGrade": {"zh-CN": "良好"},
                    "calculatedScore": "85.00",
                    "decisionReason": "formal correction",
                }
            )
        return HrResultRevision.objects.create(
            tenant_id=self.tenant_id,
            result=result,
            correction_no=f"REV-{uuid.uuid4().hex}",
            previous_version=1,
            new_version=2,
            revision_type=revision_type,
            reason="authorized correction",
            before_snapshot_json=before,
            after_snapshot_json=after,
            effective_at=effective_at
            or datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc),
            sealed_at=effective_at
            or datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc),
        )

    def test_lists_only_exact_staff_finalized_results_inside_as_of(self):
        expected = self._result()
        self._result(finalized_at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc))
        other_person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="other",
        )
        other_staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=other_person,
            staff_no=f"OTHER-{uuid.uuid4().hex}",
        )
        self._result(staff=other_staff)

        rows = list_finalized_assessment_evidence(
            tenant_id=self.tenant_id,
            person_id=self.person.id,
            staff_id=self.staff.id,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual([row.result_id for row in rows], [expected.id])
        self.assertEqual(rows[0].staff_id, self.staff.id)
        self.assertEqual(rows[0].snapshot()["calculatedScore"], "91.00")
        self.assertEqual(
            rows[0].snapshot()["calculationHash"], expected.calculation_hash
        )

    def test_person_staff_mismatch_is_unavailable_not_empty(self):
        other_person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="mismatch",
        )
        with self.assertRaises(AssessmentEvidenceUnavailable) as cm:
            list_finalized_assessment_evidence(
                tenant_id=self.tenant_id,
                person_id=other_person.id,
                staff_id=self.staff.id,
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")

    def test_effective_correction_is_the_only_downstream_version(self):
        result = self._result()
        revision = self._revision(result)

        before = get_finalized_assessment_evidence(
            tenant_id=self.tenant_id,
            person_id=self.person.id,
            result_id=result.id,
            as_of=date(2026, 8, 1),
        )
        after = get_finalized_assessment_evidence(
            tenant_id=self.tenant_id,
            person_id=self.person.id,
            result_id=result.id,
            as_of=date(2026, 8, 3),
        )

        self.assertEqual(before.result_version_no, 1)
        self.assertEqual(before.grade_code, "A")
        self.assertEqual(after.result_version_no, 2)
        self.assertEqual(after.grade_code, "B")
        self.assertEqual(after.content_hash, revision.content_hash)
        self.assertEqual(after.source_result_content_hash, result.content_hash)
        self.assertEqual(after.snapshot()["revisionId"], str(revision.id))

    def test_effective_revocation_is_not_exposed_as_formal_evidence(self):
        result = self._result()
        self._revision(result, revision_type="REVOCATION")

        self.assertEqual(
            list_finalized_assessment_evidence(
                tenant_id=self.tenant_id,
                person_id=self.person.id,
                staff_id=self.staff.id,
                as_of=date(2026, 8, 3),
            ),
            (),
        )
        with self.assertRaises(AssessmentEvidenceUnavailable) as cm:
            get_finalized_assessment_evidence(
                tenant_id=self.tenant_id,
                person_id=self.person.id,
                result_id=result.id,
                as_of=date(2026, 8, 3),
            )
        self.assertEqual(cm.exception.code, "FINAL_ASSESSMENT_RESULT_REVOKED")

    def test_datetime_is_rejected_in_date_only_as_of_contract(self):
        with self.assertRaises(AssessmentEvidenceUnavailable) as cm:
            list_finalized_assessment_evidence(
                tenant_id=self.tenant_id,
                person_id=self.person.id,
                staff_id=self.staff.id,
                as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(cm.exception.code, "AS_OF_REQUIRED")
