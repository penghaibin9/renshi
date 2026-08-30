from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_assessment.public import PROVIDER_VERSION
from hr_staff.models import HrPerson, HrStaffMaster
from hr_title.models import TitleApplicationCase, TitleMaterialSnapshot
from hr_title.services.material_service import TitleMaterialError, TitleMaterialService


class Hr12ToHr13MaterialProviderTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=77, legal_name="跨域考核证据教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=self.person,
            staff_no="T-HR12-HR13-001",
        )
        self.assessment_case = HrAssessmentCase.objects.create(
            tenant_id=77,
            assessment_type="ANNUAL",
            staff_id=self.staff.id,
            status="FINALIZED",
        )
        self.result = HrFinalAssessmentResult.objects.create(
            tenant_id=77,
            case_id=self.assessment_case.id,
            assessment_type="ANNUAL",
            grade_code="A",
            display_grade_snapshot_json={"zh-CN": "优秀"},
            calculated_score=Decimal("93.25"),
            decision_reason="集体审定通过",
            finalized_at=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
            result_version_no=2,
            status="FINALIZED",
        )
        self.title_case = TitleApplicationCase.objects.create(
            tenant_id=77,
            case_no="TITLE-HR12-001",
            person_id=self.person.id,
            policy_version_id=self.person.id,
            batch_no="TITLE-2026",
            requested_title_code="ASSOCIATE_PROFESSOR",
            status=TitleApplicationCase.Status.SUBMITTED,
        )

    def test_finalized_assessment_becomes_trusted_immutable_source_snapshot(self):
        service = TitleMaterialService(77, actor_user_id=9)

        first = service.attach_hr12_final_assessment(
            application_case_id=self.title_case.id,
            assessment_result_id=self.result.id,
            material_no="MAT-HR12-001",
            as_of=date(2026, 8, 1),
        )
        replay = service.attach_hr12_final_assessment(
            application_case_id=self.title_case.id,
            assessment_result_id=self.result.id,
            material_no="MAT-HR12-001",
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(first.id, replay.id)
        self.assertEqual(first.source_domain, "HR12")
        self.assertEqual(first.source_ref, str(self.result.id))
        self.assertEqual(first.source_version, PROVIDER_VERSION)
        self.assertEqual(first.content_hash, self.result.content_hash)
        self.assertEqual(first.snapshot_json["gradeCode"], "A")
        self.assertEqual(first.snapshot_json["calculatedScore"], "93.25")
        self.assertEqual(first.snapshot_json["staffId"], str(self.staff.id))
        self.assertEqual(
            TitleMaterialSnapshot.objects.filter(tenant_id=77, source_domain="HR12").count(),
            1,
        )

    def test_result_from_another_person_is_rejected(self):
        other_person = HrPerson.objects.create(tenant_id=77, legal_name="另一位教师")
        HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=other_person,
            staff_no="T-HR12-HR13-002",
        )
        other_title_case = TitleApplicationCase.objects.create(
            tenant_id=77,
            case_no="TITLE-HR12-002",
            person_id=other_person.id,
            policy_version_id=other_person.id,
            batch_no="TITLE-2026",
            requested_title_code="PROFESSOR",
            status=TitleApplicationCase.Status.SUBMITTED,
        )

        with self.assertRaises(TitleMaterialError) as cm:
            TitleMaterialService(77).attach_hr12_final_assessment(
                application_case_id=other_title_case.id,
                assessment_result_id=self.result.id,
                material_no="MAT-HR12-WRONG-PERSON",
                as_of=date(2026, 8, 1),
            )

        self.assertEqual(cm.exception.code, "ASSESSMENT_RESULT_IDENTITY_MISMATCH")
        self.assertFalse(
            TitleMaterialSnapshot.objects.filter(
                tenant_id=77, material_no="MAT-HR12-WRONG-PERSON"
            ).exists()
        )

    def test_cross_tenant_and_future_result_fail_closed(self):
        with self.assertRaises(TitleMaterialError) as cm:
            TitleMaterialService(88).attach_hr12_final_assessment(
                application_case_id=self.title_case.id,
                assessment_result_id=self.result.id,
                material_no="MAT-CROSS-TENANT",
                as_of=date(2026, 8, 1),
            )
        self.assertEqual(cm.exception.code, "TITLE_CASE_NOT_FOUND")

        with self.assertRaises(TitleMaterialError) as cm:
            TitleMaterialService(77).attach_hr12_final_assessment(
                application_case_id=self.title_case.id,
                assessment_result_id=self.result.id,
                material_no="MAT-FUTURE",
                as_of=date(2026, 7, 31),
            )
        self.assertEqual(cm.exception.code, "FINAL_ASSESSMENT_RESULT_UNAVAILABLE")

    def test_non_final_result_is_never_imported_as_formal_evidence(self):
        draft_case = HrAssessmentCase.objects.create(
            tenant_id=77,
            assessment_type="SPECIAL",
            staff_id=self.staff.id,
            status="PROPOSED",
        )
        draft_result = HrFinalAssessmentResult.objects.create(
            tenant_id=77,
            case_id=draft_case.id,
            assessment_type="SPECIAL",
            grade_code="B",
            finalized_at=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
            result_version_no=1,
            status="REVISED",
        )

        with self.assertRaises(TitleMaterialError) as cm:
            TitleMaterialService(77).attach_hr12_final_assessment(
                application_case_id=self.title_case.id,
                assessment_result_id=draft_result.id,
                material_no="MAT-NON-FINAL",
                as_of=date(2026, 8, 1),
            )

        self.assertEqual(cm.exception.code, "FINAL_ASSESSMENT_RESULT_UNAVAILABLE")
