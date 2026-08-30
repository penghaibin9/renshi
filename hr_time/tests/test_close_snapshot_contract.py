from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from hr_time.enums import AttendanceStatus
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.close import HrPayrollTimeBasis, HrTimeClosePeriod, HrTimeCloseSnapshot
from hr_time.services.close_service import CloseService


class CloseSnapshotContractTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(username="snapshot-reopen-requester")
        self.period = HrTimeClosePeriod.objects.create(
            tenant_id=71,
            period_type="MONTHLY",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            close_rule_version="school-time-close-2026.1",
        )
        HrAttendanceDayFact.objects.create(
            tenant_id=71,
            staff_master_id=9001,
            business_date=date(2026, 8, 3),
            policy_version_id=81,
            calendar_version_id=91,
            schedule_snapshot_json={"shiftVersion": "DAY-1"},
            expected_minutes=480,
            actual_minutes=480,
            credited_minutes=480,
            status=AttendanceStatus.PRESENT,
            evaluation_version=3,
            source_pair_ids=[101, 102],
        )

    def test_close_materializes_signed_scope_and_all_source_hashes(self):
        snapshot = CloseService.close(tenant_id=71, period=self.period)

        self.assertEqual(snapshot.metric_definition_version, "2.0")
        self.assertEqual(snapshot.policy_versions, ["81"])
        self.assertEqual(snapshot.calendar_versions, ["91"])
        self.assertEqual(snapshot.staff_count, 1)
        self.assertEqual(len(snapshot.attendance_fact_hash), 64)
        self.assertEqual(len(snapshot.leave_ledger_hash), 64)
        self.assertEqual(len(snapshot.overtime_fact_hash), 64)
        self.assertEqual(len(snapshot.close_summary_json["snapshotHash"]), 64)
        self.assertEqual(len(snapshot.close_summary_json["personnelScopeHash"]), 64)
        self.assertEqual(len(snapshot.close_summary_json["basisHash"]), 64)
        self.assertEqual(snapshot.close_summary_json["sealedBy"], "SYSTEM")

        basis = HrPayrollTimeBasis.objects.get(close_snapshot=snapshot, staff_master_id=9001)
        self.assertEqual(basis.regular_work_minutes, 480)

    def test_closed_snapshot_and_payroll_basis_reject_model_and_queryset_tamper(self):
        snapshot = CloseService.close(tenant_id=71, period=self.period)
        basis = HrPayrollTimeBasis.objects.get(close_snapshot=snapshot, staff_master_id=9001)

        snapshot.staff_count = 99
        with self.assertRaises(ValidationError):
            snapshot.save()
        with self.assertRaises(ValidationError):
            HrTimeCloseSnapshot.objects.filter(pk=snapshot.pk).update(staff_count=99)
        with self.assertRaises(ValidationError):
            snapshot.delete()

        basis.regular_work_minutes = 1
        with self.assertRaises(ValidationError):
            basis.save()
        with self.assertRaises(ValidationError):
            HrPayrollTimeBasis.objects.filter(pk=basis.pk).update(regular_work_minutes=1)
        with self.assertRaises(ValidationError):
            HrPayrollTimeBasis.objects.filter(pk=basis.pk).delete()

        CloseService.request_reopen(
            tenant_id=71,
            period=self.period,
            reason="补录更正",
            actor_user=self.requester,
            idempotency_key="snapshot-tamper-reopen",
        )
        basis.regular_work_minutes = 2
        with self.assertRaises(ValidationError):
            basis.save()
        with self.assertRaises(ValidationError):
            HrPayrollTimeBasis.objects.filter(pk=basis.pk).update(regular_work_minutes=2)
