"""HR12 list public-contract evidence tests."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_assessment.public import (
    AssessmentEvidenceUnavailable,
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
            content_hash="b" * 64,
            status=status,
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
