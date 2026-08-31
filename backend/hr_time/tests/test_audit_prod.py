"""
hr_time/tests/test_audit_prod.py

生产级审计回归测试（基于 S1-S9 代码深度审查后的加固验证）：

1. 月结硬闸门端到端：close 后 evaluate/update/delete 全部拒绝；reopen 后解冻可更正
2. queryset 层防篡改：
   - HrRawTimeEvent queryset.update/delete 拒绝（append-only 双保险）
   - HrAttendanceDayFact finalized 行 queryset.update 事实字段拒绝
   - HrTimePolicyVersion / HrLeavePolicyVersion queryset.update/delete 拒绝
3. 跨租户/跨人员事件配对被拒
4. 敏感假别 reason_text 读取控制
"""

from datetime import date, datetime, time, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from hr_time.enums import (
    AttendanceStatus,
    CalendarDayType,
    LeaveCategory,
    LeaveRequestStatus,
    LeaveUnit,
    PairingStatus,
    PolicyStatus,
    TimeEventSourceType,
    TimeEventType,
)
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.calendar import HrCalendarDay, HrWorkCalendar, HrWorkCalendarVersion
from hr_time.models.close import HrTimeClosePeriod
from hr_time.models.event import (
    HrAttendanceDevice,
    HrRawTimeEvent,
    HrTimeEventPair,
    HrTimeEventSource,
)
from hr_time.models.leave import (
    HrLeaveAccount,
    HrLeavePolicyPack,
    HrLeavePolicyVersion,
    HrLeaveType,
)
from hr_time.models.leave_request import HrLeaveRequest
from hr_time.models.policy import HrTimePolicyPack, HrTimePolicyVersion
from hr_time.services.calendar_service import CalendarService
from hr_time.services.close_service import CloseService, CloseServiceError
from hr_time.services.evaluator import AttendanceEvaluator, EvaluatorError
from hr_time.services.leave_account_service import LeaveAccountService
from hr_time.services.leave_request_service import LeaveRequestError, LeaveRequestService

D = date(2026, 8, 10)
D31 = date(2026, 8, 31)


class MonthCloseHardGateTests(TestCase):
    """月结硬闸门端到端：冻结后一切修改被拒，reopen 后可更正。"""

    def setUp(self):
        User = get_user_model()
        self.requester = User.objects.create_user(username="audit-reopen-requester")
        self.approver = User.objects.create_user(username="audit-reopen-approver")
        self.fact = HrAttendanceDayFact.objects.create(
            tenant_id=1, staff_master_id=100, business_date=D,
            status=AttendanceStatus.PRESENT, expected_minutes=480,
            actual_minutes=480, credited_minutes=480,
        )
        self.period = HrTimeClosePeriod.objects.create(
            tenant_id=1, start_date=date(2026, 8, 1), end_date=D31,
            period_type="MONTHLY",
        )

    def test_close_freezes_and_evaluator_rejects(self):
        CloseService.close(tenant_id=1, period=self.period)
        self.fact.refresh_from_db()
        self.assertTrue(self.fact.finalized)
        # 评估器拒绝覆盖（月结硬闸门）
        with self.assertRaises(EvaluatorError):
            AttendanceEvaluator.evaluate_day(
                tenant_id=1, staff_master_id=100, business_date=D,
            )

    def test_close_blocks_queryset_tamper(self):
        CloseService.close(tenant_id=1, period=self.period)
        # 直接 bulk update 事实字段 → 拒绝
        with self.assertRaises(ValidationError):
            HrAttendanceDayFact.objects.filter(
                tenant_id=1, business_date__range=(self.period.start_date, self.period.end_date)
            ).update(credited_minutes=999)
        # 实例 save 改事实字段 → 拒绝
        self.fact.refresh_from_db()
        self.fact.credited_minutes = 999
        with self.assertRaises(ValidationError):
            self.fact.save()
        # delete → 拒绝
        with self.assertRaises(ValidationError):
            self.fact.delete()

    def test_reopen_unfreezes_and_correction_allowed(self):
        CloseService.close(tenant_id=1, period=self.period)
        batch = CloseService.request_reopen(
            tenant_id=1,
            period=self.period,
            reason="补录",
            actor_user=self.requester,
            idempotency_key="audit-reopen-1",
        )
        self.fact.refresh_from_db()
        self.assertTrue(self.fact.finalized)
        CloseService.approve_reopen(
            tenant_id=1,
            period=self.period,
            batch=batch,
            actor_user=self.approver,
        )
        self.fact.refresh_from_db()
        self.assertFalse(self.fact.finalized)
        # 解冻后可更正（evaluator force 重算）
        result = AttendanceEvaluator.evaluate_day(
            tenant_id=1, staff_master_id=100, business_date=D, force=True,
        )
        self.assertEqual(result.fact.evaluation_version, 2)
        # reclose 再次冻结
        CloseService.reclose(tenant_id=1, period=self.period, batch=batch)
        self.fact.refresh_from_db()
        self.assertTrue(self.fact.finalized)

    def test_reopen_requires_closed(self):
        period = HrTimeClosePeriod.objects.create(
            tenant_id=1, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30),
        )
        with self.assertRaises(CloseServiceError):
            CloseService.request_reopen(
                tenant_id=1,
                period=period,
                reason="x",
                actor_user=self.requester,
                idempotency_key="audit-open-period",
            )


class AppendOnlyQuerysetTests(TestCase):
    def setUp(self):
        self.source = HrTimeEventSource.objects.create(
            tenant_id=1, source_type=TimeEventSourceType.BIOMETRIC,
            provider="zk", device_ref="DEV-1",
        )

    def test_raw_event_queryset_update_rejected(self):
        HrRawTimeEvent.objects.create(
            tenant_id=1, staff_master_id=100, event_type=TimeEventType.IN,
            event_at_utc=datetime(2026, 8, 9, 1, 0, tzinfo=dt_tz.utc),
            event_timezone="Asia/Shanghai",
            local_event_at=datetime(2026, 8, 9, 9, 0, tzinfo=dt_tz.utc),
            source=self.source, source_event_id="E1", dedupe_key="E1",
            raw_payload_hash="a",
        )
        with self.assertRaises(ValidationError):
            HrRawTimeEvent.objects.filter(tenant_id=1).update(trust_level=9)
        with self.assertRaises(ValidationError):
            HrRawTimeEvent.objects.filter(tenant_id=1).delete()
        self.assertEqual(HrRawTimeEvent.objects.filter(tenant_id=1).count(), 1)


class VersionQuerysetTests(TestCase):
    def test_policy_version_queryset_update_rejected(self):
        pack = HrTimePolicyPack.objects.create(tenant_id=1, code="P1", name="x")
        HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack, version_no=1,
            status=PolicyStatus.DRAFT, effective_from=D,
        )
        with self.assertRaises(ValidationError):
            HrTimePolicyVersion.objects.filter(tenant_id=1).update(version_no=2)
        with self.assertRaises(ValidationError):
            HrTimePolicyVersion.objects.filter(tenant_id=1).delete()

    def test_leave_policy_version_queryset_update_rejected(self):
        lt = HrLeaveType.objects.create(
            tenant_id=1, code="ANNUAL", name="年假",
            category=LeaveCategory.ANNUAL, unit=LeaveUnit.DAYS,
        )
        pack = HrLeavePolicyPack.objects.create(tenant_id=1, code="LP1", name="x")
        HrLeavePolicyVersion.objects.create(
            tenant_id=1, leave_policy_pack=pack, leave_type=lt, version_no=1,
            status=PolicyStatus.DRAFT, effective_from=D,
        )
        with self.assertRaises(ValidationError):
            HrLeavePolicyVersion.objects.filter(tenant_id=1).update(version_no=2)


class EventPairValidationTests(TestCase):
    def setUp(self):
        self.source_a = HrTimeEventSource.objects.create(
            tenant_id=1, source_type=TimeEventSourceType.BIOMETRIC,
            provider="zk", device_ref="A",
        )
        self.source_b = HrTimeEventSource.objects.create(
            tenant_id=2, source_type=TimeEventSourceType.BIOMETRIC,
            provider="zk", device_ref="B",
        )

    def _event(self, tenant, source, staff, etype, evid):
        return HrRawTimeEvent.objects.create(
            tenant_id=tenant, staff_master_id=staff, event_type=etype,
            event_at_utc=datetime(2026, 8, 9, 1, 0, tzinfo=dt_tz.utc),
            event_timezone="Asia/Shanghai",
            local_event_at=datetime(2026, 8, 9, 9, 0, tzinfo=dt_tz.utc),
            source=source, source_event_id=evid, dedupe_key=evid,
            raw_payload_hash=evid,
        )

    def test_cross_tenant_pair_rejected(self):
        in_ev = self._event(1, self.source_a, 100, TimeEventType.IN, "I1")
        out_ev = self._event(2, self.source_b, 100, TimeEventType.OUT, "O1")
        pair = HrTimeEventPair(
            tenant_id=1, in_event=in_ev, out_event=out_ev,
            pairing_status=PairingStatus.PAIRED,
            shift_business_date=D, duration_minutes=480,
        )
        with self.assertRaises(ValidationError):
            pair.clean()

    def test_cross_person_pair_rejected(self):
        in_ev = self._event(1, self.source_a, 100, TimeEventType.IN, "I2")
        out_ev = self._event(1, self.source_a, 200, TimeEventType.OUT, "O2")
        pair = HrTimeEventPair(
            tenant_id=1, in_event=in_ev, out_event=out_ev,
            pairing_status=PairingStatus.PAIRED,
            shift_business_date=D, duration_minutes=480,
        )
        with self.assertRaises(ValidationError):
            pair.clean()

    def test_same_person_pair_allowed(self):
        in_ev = self._event(1, self.source_a, 100, TimeEventType.IN, "I3")
        out_ev = self._event(1, self.source_a, 100, TimeEventType.OUT, "O3")
        pair = HrTimeEventPair(
            tenant_id=1, in_event=in_ev, out_event=out_ev,
            pairing_status=PairingStatus.PAIRED,
            shift_business_date=D, duration_minutes=480,
        )
        pair.clean()  # 不抛错


class SensitiveReasonTests(TestCase):
    def setUp(self):
        self.sensitive_lt = HrLeaveType.objects.create(
            tenant_id=1, code="SICK", name="病假",
            category=LeaveCategory.SICK, unit=LeaveUnit.DAYS,
            sensitive_reason=True,
        )
        self.acct = HrLeaveAccount.objects.create(
            tenant_id=1, staff_master_id=100,
            leave_type=self.sensitive_lt, account_year=2026,
        )
        LeaveAccountService.grant(
            tenant_id=1, staff_master_id=100, leave_type_id=self.sensitive_lt.id,
            account_year=2026, amount=5, effective_date=D,
        )

    def test_sensitive_reason_requires_access(self):
        req = HrLeaveRequest.objects.create(
            tenant_id=1, staff_master_id=100, leave_type=self.sensitive_lt,
            start_at=D, end_at=D,
            requested_amount=1, unit="DAYS", account=self.acct,
            reason_text="诊断详情", status=LeaveRequestStatus.APPROVED,
        )
        # 无敏感权限 → 拒绝读取
        with self.assertRaises(LeaveRequestError) as ctx:
            LeaveRequestService.assert_reason_readable(req, has_sensitive_access=False)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        # 有敏感权限 → 允许
        LeaveRequestService.assert_reason_readable(req, has_sensitive_access=True)
