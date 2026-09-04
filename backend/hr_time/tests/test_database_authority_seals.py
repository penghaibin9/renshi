from datetime import date, timedelta
from unittest import SkipTest

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from hr_time.enums import OvertimeSettlementMode, TimeEventType
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.close import HrPayrollTimeBasis, HrTimeClosePeriod, HrTimeCloseSnapshot
from hr_time.models.event import HrRawTimeEvent, HrTimeEventSource
from hr_time.models.leave import HrLeaveAccount, HrLeaveType
from hr_time.models.overtime import HrOvertimeFact
from hr_time.models.policy import HrTimePolicyPack, HrTimePolicyVersion
from hr_time.services.close_service import CloseService
from hr_time.services.leave_account_service import LeaveAccountService
from hr_time.services.overtime_service import OvertimeService


class Hr11MySQLAuthoritySealTests(TestCase):
    """ORM guards are not the authority boundary; direct SQL must fail too."""

    @classmethod
    def setUpClass(cls):
        if connection.vendor != "mysql":
            raise SkipTest("HR11 production database seals are MySQL-only")
        super().setUpClass()

    def _database_error(self, sql, params):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)

    def test_raw_event_identity_is_immutable_below_orm(self):
        source = HrTimeEventSource.objects.create(
            tenant_id=501,
            source_type="API",
            provider="seal-test",
            device_ref="source-1",
            trust_level=3,
        )
        now = timezone.now()
        event = HrRawTimeEvent.objects.create(
            tenant_id=501,
            staff_master_id=10,
            event_type=TimeEventType.IN,
            event_at_utc=now,
            local_event_at=now,
            source=source,
            dedupe_key="seal-event-1",
            raw_payload_hash="a" * 64,
            trust_level=3,
        )
        self._database_error(
            "UPDATE hr_time_hrrawtimeevent SET staff_master_id=%s WHERE id=%s",
            [11, event.id],
        )
        self._database_error(
            "DELETE FROM hr_time_hrrawtimeevent WHERE id=%s", [event.id]
        )

    def test_leave_ledger_is_append_only_below_orm(self):
        leave_type = HrLeaveType.objects.create(
            tenant_id=502, code="ANNUAL", name="年休假"
        )
        HrLeaveAccount.objects.create(
            tenant_id=502,
            staff_master_id=20,
            leave_type=leave_type,
            account_year=2026,
        )
        entry = LeaveAccountService.grant(
            tenant_id=502,
            staff_master_id=20,
            leave_type_id=leave_type.id,
            account_year=2026,
            amount=5,
            effective_date=date(2026, 8, 1),
        )
        self._database_error(
            "UPDATE hr_time_hrleaveledgerentry SET amount=%s WHERE id=%s",
            [9, entry.id],
        )
        self._database_error(
            "DELETE FROM hr_time_hrleaveledgerentry WHERE id=%s", [entry.id]
        )

    def test_close_snapshot_and_basis_are_immutable_below_orm(self):
        period = HrTimeClosePeriod.objects.create(
            tenant_id=503,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        HrAttendanceDayFact.objects.create(
            tenant_id=503,
            staff_master_id=30,
            business_date=date(2026, 8, 3),
            actual_minutes=480,
            credited_minutes=480,
            status="PRESENT",
        )
        snapshot = CloseService.close(tenant_id=503, period=period)
        basis = HrPayrollTimeBasis.objects.get(close_snapshot=snapshot)
        self._database_error(
            "UPDATE hr_time_hrtimeclosesnapshot SET staff_count=%s WHERE id=%s",
            [999, snapshot.id],
        )
        self._database_error(
            "UPDATE hr_time_hrpayrolltimebasis SET regular_work_minutes=%s WHERE id=%s",
            [1, basis.id],
        )

    def test_day_fact_cannot_be_fake_finalized(self):
        fact = HrAttendanceDayFact.objects.create(
            tenant_id=504,
            staff_master_id=40,
            business_date=date(2026, 8, 3),
            actual_minutes=60,
            credited_minutes=60,
            status="PRESENT",
        )
        self._database_error(
            "UPDATE hr_time_hrattendancedayfact SET finalized=1 WHERE id=%s",
            [fact.id],
        )

    def test_closed_period_cannot_be_downgraded_below_orm(self):
        period = HrTimeClosePeriod.objects.create(
            tenant_id=508,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        CloseService.close(tenant_id=508, period=period)
        self._database_error(
            "UPDATE hr_time_hrtimecloseperiod SET status='OPEN' WHERE id=%s",
            [period.id],
        )

    def test_policy_cannot_be_fake_published_below_orm(self):
        pack = HrTimePolicyPack.objects.create(
            tenant_id=509, code="DB-SEAL", name="数据库封印测试"
        )
        version = HrTimePolicyVersion.objects.create(
            tenant_id=509,
            policy_pack=pack,
            version_no=1,
            effective_from=date(2026, 8, 1),
        )
        self._database_error(
            "UPDATE hr_time_hrtimepolicyversion SET status='PUBLISHED' WHERE id=%s",
            [version.id],
        )

    def test_overtime_requires_trusted_verification_and_then_freezes(self):
        verifier = get_user_model().objects.create_user(username="hr11-db-seal-verifier")
        now = timezone.now()
        fact = HrOvertimeFact.objects.create(
            tenant_id=505,
            staff_master_id=50,
            actual_start_at=now,
            actual_end_at=now + timedelta(hours=2),
            actual_minutes=120,
            eligible_minutes=90,
        )
        self._database_error(
            "UPDATE hr_time_hrovertimefact SET verification_status='VERIFIED', "
            "settlement_mode='COMP_TIME' WHERE id=%s",
            [fact.id],
        )
        verified = OvertimeService.verify(
            fact=fact,
            actor_user=verifier,
            settlement_mode=OvertimeSettlementMode.COMP_TIME,
            evidence_source="attendance-pair:db-seal",
            idempotency_key="db-seal-verify-1",
        )
        self.assertTrue(verified.verify_receipt())
        self._database_error(
            "UPDATE hr_time_hrovertimefact SET eligible_minutes=%s WHERE id=%s",
            [1, fact.id],
        )

    def test_cross_tenant_close_snapshot_bulk_insert_is_rejected(self):
        local = HrTimeClosePeriod.objects.create(
            tenant_id=506,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                HrTimeCloseSnapshot.objects.bulk_create(
                    [HrTimeCloseSnapshot(tenant_id=507, period=local)]
                )
