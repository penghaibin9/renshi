from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import TestCase

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult
from hr_qualification.constants import ProviderStatus
from hr_qualification.providers.hr12 import PROVIDER_VERSION, Hr12AssessmentProvider
from hr_staff.models import HrPerson, HrStaffMaster


class Hr12QualificationProviderTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=77, legal_name="HR12证据教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=self.person,
            staff_no="T-HR12-001",
        )
        self.case = HrAssessmentCase.objects.create(
            tenant_id=77,
            assessment_type="ANNUAL",
            staff_id=self.staff.id,
            status="FINALIZED",
        )

    def _result(
        self,
        *,
        finalized_at=datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc),
        status="FINALIZED",
        case_id=None,
        tenant_id=77,
    ):
        return HrFinalAssessmentResult.objects.create(
            tenant_id=tenant_id,
            case_id=case_id or self.case.id,
            assessment_type="ANNUAL",
            grade_code="A",
            display_grade_snapshot_json={"zh-CN": "优秀"},
            calculated_score=Decimal("92.50"),
            decision_reason="集体审定通过",
            finalized_at=finalized_at,
            result_version_no=1,
            status=status,
        )

    def test_provider_reads_only_finalized_results_at_asof_boundary(self):
        expected = self._result()
        future_case = HrAssessmentCase.objects.create(
            tenant_id=77,
            assessment_type="SPECIAL",
            staff_id=self.staff.id,
            status="FINALIZED",
        )
        self._result(
            case_id=future_case.id,
            finalized_at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        )
        non_final_case = HrAssessmentCase.objects.create(
            tenant_id=77,
            assessment_type="TERM",
            staff_id=self.staff.id,
            status="PROPOSED",
        )
        self._result(case_id=non_final_case.id, status="REVISED")

        result = Hr12AssessmentProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.provider_version, PROVIDER_VERSION)
        self.assertEqual([item.source_object_id for item in result.items], [str(expected.id)])
        self.assertEqual(result.items[0].quantitative_value, 92.5)
        self.assertEqual(result.items[0].snapshot_json["calculatedScore"], "92.50")

    def test_cross_tenant_and_wrong_person_identity_fail_closed(self):
        result = Hr12AssessmentProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=88,
            as_of=date(2026, 8, 1),
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_IDENTITY_MAPPING_UNAVAILABLE")

        other = HrPerson.objects.create(tenant_id=77, legal_name="另一位教师")
        result = Hr12AssessmentProvider().provide(
            person_id=other.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)

    def test_missing_staff_identity_is_unavailable_not_fake_empty(self):
        result = Hr12AssessmentProvider().provide(
            person_id=self.person.id,
            staff_master_id=None,
            tenant_id=77,
            as_of=date(2026, 8, 1),
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.items, [])

    def test_unknown_source_version_fails_closed(self):
        result = Hr12AssessmentProvider().provide(
            person_id=self.person.id,
            staff_master_id=self.staff.id,
            tenant_id=77,
            as_of=date(2026, 8, 1),
            source_version="legacy-placeholder-v0",
        )
        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertEqual(result.errors[0].code, "SOURCE_VERSION_UNSUPPORTED")
