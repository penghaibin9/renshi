"""
hr_time/services/ingestion.py

S4 事件接入管线（总册 §57-58）：

receive → auth source → tenant resolve → schema validate → person map
→ time normalize → dedupe → persist raw event → (pair/evaluate 异步)

幂等（§58）：
- 优先 (source, source_event_id)；
- 无 source_event_id 时用复合 dedupe_key：provider+device+person+type+at+hash；
- 重复 webhook 返回已存在事件（幂等 ack），不重复生成工时。

时区（§142）：事件时间统一存 UTC；同时保存事件原始时区与本地时间。
学校时区由 HrTimeContext 提供，禁止服务器本地时间当业务时间。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone as dt_tz
from typing import Optional

from django.utils import timezone

from hr_time.enums import TimeEventIngestStatus, TimeEventType
from hr_time.models.event import (
    HrAttendanceDevice,
    HrRawTimeEvent,
    HrTimeEventSource,
)


class IngestionError(Exception):
    def __init__(self, code: str, message: str, details=None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class IngestResult:
    event: Optional[HrRawTimeEvent] = None
    status: str = ""  # CREATED / DUPLICATE / REJECTED
    code: str = "OK"


def _stable_dumps(data) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_payload_hash(payload) -> str:
    return hashlib.sha256(_stable_dumps(payload).encode("utf-8")).hexdigest()


def build_dedupe_key(
    *,
    provider: str,
    device_ref: str,
    staff_master_id: int,
    event_type: str,
    local_event_at: datetime,
    payload_hash: str,
) -> str:
    """无 source_event_id 时的复合幂等键（§58）。"""
    raw = (
        f"{provider}|{device_ref}|{staff_master_id}|{event_type}|"
        f"{local_event_at.isoformat()}|{payload_hash}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_event_time(
    *, local_event_at: datetime, timezone_name: str = "Asia/Shanghai"
) -> tuple[datetime, datetime]:
    """
    将本地事件时间规范化为 UTC 与本地 datetime（aware）。

    返回 (event_at_utc, local_event_at_aware)。
    本地时间缺失时：以当前 UTC 时间视为学校时区本地时间。
    禁止 naive datetime 落库（§142）。
    """
    import zoneinfo

    try:
        tz = zoneinfo.ZoneInfo(timezone_name)
    except Exception:
        tz = zoneinfo.ZoneInfo("Asia/Shanghai")

    if local_event_at is None:
        now = timezone.now()
        return now, now.astimezone(tz)

    if timezone.is_aware(local_event_at):
        local_aware = local_event_at.astimezone(tz)
    else:
        local_aware = local_event_at.replace(tzinfo=tz)
    return local_aware.astimezone(dt_tz.utc), local_aware


class IngestionService:
    @staticmethod
    def _resolve_source(
        *, tenant_id: int, source_type: str, provider: str = "", device_ref: str = ""
    ) -> HrTimeEventSource:
        """按 (tenant, source_type, provider, device_ref) 解析来源；不存在则拒绝（fail-closed）。"""
        source = (
            HrTimeEventSource.objects.filter(
                tenant_id=tenant_id,
                source_type=source_type,
                provider=provider,
                device_ref=device_ref,
                active=True,
            ).first()
        )
        if source is None:
            raise IngestionError(
                "TIME_EVENT_SOURCE_INVALID",
                f"未知事件来源: {source_type}/{provider}/{device_ref}（fail-closed）",
            )
        return source

    @classmethod
    def ingest(
        cls,
        *,
        tenant_id: int,
        source_type: str,
        staff_master_id: int,
        event_type: str,
        local_event_at: datetime,
        payload: Optional[dict] = None,
        source_event_id: str = "",
        provider: str = "",
        device_ref: str = "",
        device_id: Optional[int] = None,
        timezone_name: str = "Asia/Shanghai",
        location_ref: str = "",
    ) -> IngestResult:
        """单条事件接入（同步落库，配对/评估由异步任务后续处理）。"""
        # 1. 来源鉴权/解析（fail-closed）
        source = cls._resolve_source(
            tenant_id=tenant_id, source_type=source_type, provider=provider, device_ref=device_ref
        )

        # 2. schema 校验
        if event_type not in TimeEventType.values:
            raise IngestionError("INVALID_REQUEST", f"非法事件类型: {event_type}")
        if not staff_master_id:
            raise IngestionError("INVALID_REQUEST", "缺少 staff_master_id")

        # 3. 时间规范化（§142：禁止 naive 落库）
        event_at_utc, local_aware = normalize_event_time(
            local_event_at=local_event_at, timezone_name=timezone_name
        )

        # 4. payload hash
        payload_hash = compute_payload_hash(payload or {})

        # 5. 幂等键
        if source_event_id:
            dedupe_key = source_event_id
        else:
            dedupe_key = build_dedupe_key(
                provider=provider or source_type,
                device_ref=device_ref,
                staff_master_id=staff_master_id,
                event_type=event_type,
                local_event_at=local_aware,
                payload_hash=payload_hash,
            )

        # 6. 去重（重复返回已存在事件，幂等 ack）
        existing = HrRawTimeEvent.objects.filter(
            tenant_id=tenant_id, source=source, dedupe_key=dedupe_key
        ).first()
        if existing is not None:
            return IngestResult(event=existing, status="DUPLICATE")

        device = None
        if device_id:
            device = HrAttendanceDevice.objects.filter(
                tenant_id=tenant_id, pk=device_id
            ).first()

        # 7. 持久化（append-only）
        event = HrRawTimeEvent.objects.create(
            tenant_id=tenant_id,
            staff_master_id=staff_master_id,
            event_type=event_type,
            event_at_utc=event_at_utc,
            event_timezone=timezone_name,
            local_event_at=local_aware,
            source=source,
            source_event_id=source_event_id,
            dedupe_key=dedupe_key,
            device=device,
            location_ref=location_ref,
            raw_payload_hash=payload_hash,
            trust_level=source.trust_level,
            ingest_status=TimeEventIngestStatus.RECEIVED,
        )
        return IngestResult(event=event, status="CREATED")
