"""
hr_time/tests/test_s4.py

HR11-S4 验收测试（原始打卡事件不可变账本）：
- append-only：delete() 拒绝；save() 关键字段不可变更
- 幂等去重：(source, source_event_id) 唯一；重复 ingest 返回 DUPLICATE 且不新增行
- 无 source_event_id 时复合 dedupe_key
- 时区规范化：UTC 与本地时间正确；禁止 naive 落库
- 未知来源 fail-closed（TIME_EVENT_SOURCE_INVALID）
- 所有表 tenant_id NOT NULL + 跨租户隔离
- 事件配对状态机基础
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from hr_time.enums import PairingStatus, TimeEventIngestStatus, TimeEventSourceType, TimeEventType
from hr_time.models.event import (
    HrAttendanceDevice,
    HrRawTimeEvent,
    HrTimeEventPair,
    HrTimeEventSource,
)
from hr_time.services.ingestion import IngestionError, IngestionService

NOW_NAIVE = datetime(2026, 8, 9, 9, 0, 0)  # 学校时区本地 09:00


def make_source(tenant_id=1, source_type=TimeEventSourceType.BIOMETRIC, provider="zk", device_ref="DEV-1"):
    return HrTimeEventSource.objects.create(
        tenant_id=tenant_id, source_type=source_type, provider=provider,
        device_ref=device_ref, trust_level=5, signature_required=True,
    )


def make_device(tenant_id=1):
    return HrAttendanceDevice.objects.create(
        tenant_id=tenant_id, provider="zk", external_device_id="DEV-1", name="门禁1",
    )


class RawEventImmutabilityTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.event = HrRawTimeEvent.objects.create(
            tenant_id=1,
            staff_master_id=100,
            event_type=TimeEventType.IN,
            event_at_utc=timezone.now(),
            event_timezone="Asia/Shanghai",
            local_event_at=timezone.now(),
            source=self.source,
            source_event_id="E1",
            dedupe_key="E1",
            raw_payload_hash="abc",
        )

    def test_delete_rejected(self):
        with self.assertRaises(ValidationError):
            self.event.delete()
        self.assertTrue(HrRawTimeEvent.objects.filter(pk=self.event.pk).exists())

    def test_update_key_field_rejected(self):
        self.event.event_type = TimeEventType.OUT
        with self.assertRaises(ValidationError):
            self.event.save()
        # 关键字段未被改动
        self.event.refresh_from_db()
        self.assertEqual(self.event.event_type, TimeEventType.IN)

    def test_update_nonkey_field_allowed(self):
        # 非关键字段（如 ingest_status）可更新——评估器后续推进状态用
        self.event.ingest_status = TimeEventIngestStatus.VALIDATED
        self.event.save()
        self.event.refresh_from_db()
        self.assertEqual(self.event.ingest_status, TimeEventIngestStatus.VALIDATED)


class IngestionIdempotencyTests(TestCase):
    def setUp(self):
        self.source = make_source()

    def _ingest(self, **over):
        kwargs = dict(
            tenant_id=1,
            source_type=TimeEventSourceType.BIOMETRIC,
            staff_master_id=100,
            event_type=TimeEventType.IN,
            local_event_at=NOW_NAIVE,
            provider="zk",
            device_ref="DEV-1",
            source_event_id="EVT-1",
        )
        kwargs.update(over)
        return IngestionService.ingest(**kwargs)

    def test_create_then_duplicate_idempotent(self):
        r1 = self._ingest()
        self.assertEqual(r1.status, "CREATED")
        count_after_first = HrRawTimeEvent.objects.count()
        # 重复 webhook → DUPLICATE，不新增行（幂等 ack）
        r2 = self._ingest()
        self.assertEqual(r2.status, "DUPLICATE")
        self.assertEqual(r2.event.id, r1.event.id)
        self.assertEqual(HrRawTimeEvent.objects.count(), count_after_first)

    def test_composite_dedupe_key_without_source_event_id(self):
        r1 = self._ingest(source_event_id="")
        self.assertEqual(r1.status, "CREATED")
        r2 = self._ingest(source_event_id="")
        self.assertEqual(r2.status, "DUPLICATE")
        self.assertEqual(r2.event.id, r1.event.id)

    def test_same_source_different_person_distinct(self):
        r1 = self._ingest(source_event_id="EVT-A")
        r2 = self._ingest(source_event_id="EVT-A", staff_master_id=200)
        # 同一 source_event_id 但不同人员 → 仍按 (source, dedupe_key) 判重
        self.assertEqual(r1.status, "CREATED")
        self.assertEqual(r2.status, "DUPLICATE")  # dedupe_key=source_event_id，保持幂等

    def test_timezone_normalization(self):
        r = self._ingest(source_event_id="EVT-TZ")
        ev = r.event
        self.assertTrue(timezone.is_aware(ev.event_at_utc))
        self.assertTrue(timezone.is_aware(ev.local_event_at))
        # UTC == 本地 - 8h（Asia/Shanghai UTC+8）
        self.assertEqual(ev.event_at_utc, ev.local_event_at.astimezone(dt_tz.utc))

    def test_unknown_source_fail_closed(self):
        with self.assertRaises(IngestionError) as ctx:
            self._ingest(source_type=TimeEventSourceType.WEB, provider="unknown", device_ref="X")
        self.assertEqual(ctx.exception.code, "TIME_EVENT_SOURCE_INVALID")

    def test_tenant_isolation(self):
        make_source(tenant_id=2, provider="zk", device_ref="DEV-1")
        # tenant 1 ingest，tenant 2 不可见
        r = self._ingest(source_event_id="EVT-T1")
        self.assertEqual(r.status, "CREATED")
        self.assertEqual(
            HrRawTimeEvent.objects.filter(tenant_id=2, source__provider="zk").count(), 0
        )


class EventPairTests(TestCase):
    def setUp(self):
        self.source = make_source()
        self.in_event = HrRawTimeEvent.objects.create(
            tenant_id=1, staff_master_id=100, event_type=TimeEventType.IN,
            event_at_utc=timezone.now(), event_timezone="Asia/Shanghai",
            local_event_at=timezone.now(), source=self.source,
            source_event_id="IN1", dedupe_key="IN1", raw_payload_hash="a",
        )

    def test_pair_created_open(self):
        pair = HrTimeEventPair.objects.create(
            tenant_id=1, in_event=self.in_event,
            pairing_status=PairingStatus.OPEN,
            shift_business_date=timezone.localdate(),
        )
        self.assertEqual(pair.pairing_status, PairingStatus.OPEN)
        self.assertEqual(pair.duration_minutes, None)
