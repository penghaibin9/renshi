import uuid
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hr10_development.constants import FactType, VerificationStatus
from hr10_development.models.development_fact import HrDevelopmentFact
from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import DevelopmentProvider, TimeSummaryProvider
from hr_staff.models import HrPerson, HrStaffMaster
from hr_time.models.close import HrPayrollTimeBasis, HrTimeClosePeriod, HrTimeCloseSnapshot


class Hr10Hr11AssessmentProviderTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(tenant_id=77, legal_name="考核证据教师")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=self.person,
            staff_no="ASSESS-PROVIDER-001",
            legacy_employee_id=501,
        )

    def _ctx(self, *, ids=None, as_of=date(2026, 8, 15), tenant_id=77):
        return ProviderContext(
            tenant_id=tenant_id,
            ids=ids if ids is not None else [self.staff.id],
            as_of=datetime(
                as_of.year,
                as_of.month,
                as_of.day,
                12,
                0,
                tzinfo=dt_timezone.utc,
            ),
        )

    def test_hr10_provider_returns_only_verified_as_of_formal_facts(self):
        fact = HrDevelopmentFact.objects.create(
            tenant_id=77,
            staff_master_id=501,
            fact_type=FactType.TRAINING_COMPLETION,
            source_case_type="TRAINING_COMPLETION",
            source_case_id=1001,
            source_revision_no=1,
            activity_type="INTERNAL_TRAINING",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
            verified_hours=Decimal("12.0"),
            verification_status=VerificationStatus.HR_VERIFIED,
            evidence_package_hash="evidence-hash-001",
            generated_at=timezone.now(),
            valid_from=date(2026, 7, 2),
        )

        result = DevelopmentProvider().fetch(self._ctx())

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.source_version, "hr10-development-fact-v1")
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0]["factId"], fact.id)
        self.assertEqual(result.data[0]["staffId"], str(self.staff.id))
        self.assertEqual(result.data[0]["verifiedHours"], "12.0")
        self.assertEqual(result.data[0]["verificationStatus"], VerificationStatus.HR_VERIFIED)

        historical = DevelopmentProvider().fetch(
            self._ctx(as_of=date(2026, 6, 30))
        )
        self.assertEqual(historical.status, ProviderStatus.OK)
        self.assertEqual(historical.data, [])

    def test_hr10_provider_exposes_identity_gap_instead_of_zero(self):
        HrDevelopmentFact.objects.create(
            tenant_id=77,
            staff_master_id=501,
            fact_type=FactType.ENTERPRISE_PRACTICE,
            source_case_type="ENTERPRISE_PRACTICE",
            source_case_id=1002,
            source_revision_no=1,
            verified_days=20,
            verification_status=VerificationStatus.HR_VERIFIED,
            generated_at=timezone.now(),
            valid_from=date(2026, 7, 1),
        )
        missing = uuid.uuid4()

        partial = DevelopmentProvider().fetch(self._ctx(ids=[self.staff.id, missing]))
        self.assertEqual(partial.status, ProviderStatus.PARTIAL)
        self.assertIn(str(missing), partial.error_message)
        self.assertEqual(len(partial.data), 1)

        cross_tenant = DevelopmentProvider().fetch(self._ctx(tenant_id=88))
        self.assertEqual(cross_tenant.status, ProviderStatus.UNAVAILABLE)
        self.assertIn("SOURCE_IDENTITY_MAPPING_UNAVAILABLE", cross_tenant.error_message)

    def _closed_time_basis(self):
        period = HrTimeClosePeriod.objects.create(
            tenant_id=77,
            period_type="MONTHLY",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            status="CLOSED",
            closed_at=timezone.now(),
        )
        snapshot = HrTimeCloseSnapshot.objects.create(
            tenant_id=77,
            period=period,
            metric_definition_version="1.0",
            attendance_fact_hash="a" * 64,
            leave_ledger_hash="b" * 64,
            overtime_fact_hash="c" * 64,
        )
        period.snapshot_id = snapshot.id
        period.save(update_fields=["snapshot_id"])
        HrPayrollTimeBasis.objects.create(
            tenant_id=77,
            close_snapshot=snapshot,
            staff_master_id=501,
            regular_work_minutes=9600,
            payable_authorized_absence_minutes=480,
            unpaid_absence_minutes=0,
            verified_overtime_minutes=180,
            comp_time_minutes=60,
            unexcused_absence_minutes=0,
            basis_version="1.0",
        )
        return period, snapshot

    def test_hr11_time_provider_reads_only_closed_snapshot_basis(self):
        period, snapshot = self._closed_time_basis()

        result = TimeSummaryProvider().fetch(self._ctx())

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.source_version, "hr11-time-close-v1")
        self.assertEqual(len(result.data), 1)
        row = result.data[0]
        self.assertEqual(row["staffId"], str(self.staff.id))
        self.assertEqual(row["regularWorkMinutes"], 9600)
        self.assertEqual(row["verifiedOvertimeMinutes"], 180)
        self.assertEqual(row["timeClose"]["timeClosePeriodId"], period.id)
        self.assertEqual(row["timeClose"]["timeCloseSnapshotId"], snapshot.id)
        self.assertEqual(row["timeClose"]["attendanceFactHash"], "a" * 64)

    def test_hr11_reopened_period_is_unavailable_not_raw_fallback(self):
        period, _snapshot = self._closed_time_basis()
        period.status = "REOPENED"
        period.save(update_fields=["status"])

        result = TimeSummaryProvider().fetch(self._ctx())

        self.assertEqual(result.status, ProviderStatus.UNAVAILABLE)
        self.assertIn("TIME_CLOSE_PERIOD_NOT_FOUND", result.error_message)
        self.assertIsNone(result.data)

    def test_hr11_missing_basis_is_partial_not_zero(self):
        self._closed_time_basis()
        missing = HrPerson.objects.create(tenant_id=77, legal_name="缺失考勤基础教师")
        missing_staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=missing,
            staff_no="ASSESS-PROVIDER-002",
            legacy_employee_id=502,
        )

        result = TimeSummaryProvider().fetch(
            self._ctx(ids=[self.staff.id, missing_staff.id])
        )

        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertIn(str(missing_staff.id), result.error_message)
        self.assertEqual(len(result.data), 1)
