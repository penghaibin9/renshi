import uuid
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr10_development.constants import FactType, VerificationStatus
from hr10_development.models.development_fact import HrDevelopmentFact
from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.provider_snapshot import HrProviderSnapshotItem, HrProviderSnapshotSet
from hr_assessment.service.evidence import EvidenceSnapshotError, ProviderEvidenceSnapshotService
from hr_assessment.services.finalization_service import AssessmentFinalizationService
from hr_staff.models import HrPerson, HrStaffMaster
from hr_time.enums import AttendanceStatus
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.close import HrTimeClosePeriod
from hr_time.services.close_service import CloseService


class ProviderEvidenceSnapshotServiceTests(TestCase):
    def setUp(self):
        self.tenant_id = 77
        self.person = HrPerson.objects.create(tenant_id=self.tenant_id, legal_name="HR12 正式证据教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=self.person,
            staff_no="HR12-SNAPSHOT-001",
            legacy_employee_id=501,
        )
        self.case = HrAssessmentCase.objects.create(
            tenant_id=self.tenant_id,
            assessment_type="ANNUAL",
            staff_id=self.staff.id,
            status="PROPOSED",
        )
        self.as_of = datetime(2026, 8, 31, 12, 0, tzinfo=dt_timezone.utc)

    def _development_fact(self):
        return HrDevelopmentFact.objects.create(
            tenant_id=self.tenant_id,
            staff_master_id=501,
            fact_type=FactType.TRAINING_COMPLETION,
            source_case_type="TRAINING_COMPLETION",
            source_case_id=12001,
            source_revision_no=1,
            activity_type="INTERNAL_TRAINING",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            verified_hours=Decimal("12.0"),
            verification_status=VerificationStatus.HR_VERIFIED,
            evidence_package_hash="hr12-provider-evidence-001",
            generated_at=timezone.now(),
            valid_from=date(2026, 8, 2),
        )

    def _closed_time_basis(self):
        period = HrTimeClosePeriod.objects.create(
            tenant_id=self.tenant_id,
            period_type="MONTHLY",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        HrAttendanceDayFact.objects.create(
            tenant_id=self.tenant_id,
            staff_master_id=501,
            business_date=date(2026, 8, 3),
            expected_minutes=9600,
            actual_minutes=9600,
            credited_minutes=9600,
            status=AttendanceStatus.PRESENT,
        )
        return CloseService.close(tenant_id=self.tenant_id, period=period)

    def test_capture_freezes_hr10_hr11_and_replay_is_idempotent(self):
        fact = self._development_fact()
        time_snapshot = self._closed_time_basis()
        service = ProviderEvidenceSnapshotService(self.tenant_id)

        first = service.capture_case(
            case_id=self.case.id,
            required_provider_names=["development", "time_summary"],
            as_of=self.as_of,
            request_id="hr12-snapshot-001",
        )
        replay = service.capture_case(
            case_id=self.case.id,
            required_provider_names=["time_summary", "development"],
            as_of=self.as_of,
            request_id="hr12-snapshot-replay",
        )

        self.case.refresh_from_db()
        self.assertEqual(first.status, "READY")
        self.assertEqual(replay.id, first.id)
        self.assertEqual(self.case.provider_snapshot_set_id, first.id)
        self.assertEqual(HrProviderSnapshotSet.objects.filter(case_id=self.case.id).count(), 1)

        items = HrProviderSnapshotItem.objects.filter(tenant_id=self.tenant_id, snapshot_set=first)
        self.assertEqual(items.count(), 2)
        development = items.get(provider_type="development")
        time_item = items.get(provider_type="time_summary")
        self.assertEqual(development.status, "VERIFIED")
        self.assertEqual(development.snapshot_json["factId"], fact.id)
        self.assertEqual(time_item.snapshot_json["timeClose"]["timeCloseSnapshotId"], time_snapshot.id)
        self.assertEqual(time_item.status, "VERIFIED")

    def test_blocked_capture_can_be_recovered_by_new_ready_version(self):
        service = ProviderEvidenceSnapshotService(self.tenant_id)
        blocked = service.capture_case(
            case_id=self.case.id,
            required_provider_names=["time_summary"],
            as_of=self.as_of,
        )
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertEqual(HrProviderSnapshotItem.objects.get(snapshot_set=blocked).status, "SOURCE_UNAVAILABLE")

        self._closed_time_basis()
        ready = service.capture_case(
            case_id=self.case.id,
            required_provider_names=["time_summary"],
            as_of=self.as_of,
        )

        self.case.refresh_from_db()
        self.assertEqual(ready.status, "READY")
        self.assertNotEqual(ready.id, blocked.id)
        self.assertEqual(self.case.provider_snapshot_set_id, ready.id)
        self.assertTrue(HrProviderSnapshotSet.objects.filter(id=blocked.id, status="BLOCKED").exists())

        blockers = AssessmentFinalizationService(self.tenant_id)._gate_blockers(
            case=self.case,
            decision_session_id=uuid.uuid4(),
        )
        codes = {item["code"] for item in blockers}
        self.assertNotIn("ASSESSMENT_PROVIDER_SNAPSHOT_REQUIRED", codes)
        self.assertNotIn("ASSESSMENT_PROVIDER_SNAPSHOT_STATE_DRIFT", codes)
        self.assertNotIn("ASSESSMENT_PROVIDER_SNAPSHOT_BLOCKED", codes)

    def test_finalization_requires_current_provider_snapshot(self):
        blockers = AssessmentFinalizationService(self.tenant_id)._gate_blockers(
            case=self.case,
            decision_session_id=uuid.uuid4(),
        )
        self.assertIn("ASSESSMENT_PROVIDER_SNAPSHOT_REQUIRED", {item["code"] for item in blockers})

    def test_cross_tenant_capture_fails_closed(self):
        with self.assertRaises(EvidenceSnapshotError) as cm:
            ProviderEvidenceSnapshotService(88).capture_case(
                case_id=self.case.id,
                required_provider_names=["development"],
                as_of=self.as_of,
            )
        self.assertEqual(cm.exception.code, "ASSESSMENT_CASE_NOT_FOUND")
