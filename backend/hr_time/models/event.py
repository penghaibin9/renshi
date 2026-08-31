"""
hr_time/models/event.py

S4 原始打卡事件账本（总册 §51-59、§188）。

- HrTimeEventSource：事件来源（BIOMETRIC/MOBILE/WEB/API/IMPORT/MANUAL，trust_level/signature/geofence）
- HrAttendanceDevice：设备注册（provider/外部 id/时区/secret_ref，密钥入 Secret Manager）
- HrRawTimeEvent：不可变事件账本（append-only）
- HrTimeEventPair：事件配对状态机（PAIRED/OPEN/AMBIGUOUS/INVALID_ORDER/CROSS_SHIFT/MANUAL_REVIEW）

铁律（总册 §51、§199）：
- 原始事件 append-only：不 hard delete、不可 UPDATE 关键字段；
- 幂等去重：(source, source_event_id) 唯一；无 source event id 时用复合 dedupe_key；
- 禁止补卡直接 UPDATE 原始事件（补卡走 Correction Case）；
- 事件时间统一存 UTC + 原始时区/local（§142），禁止 naive 当业务时间。
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_time.enums import (
    PairingStatus,
    TimeEventIngestStatus,
    TimeEventSourceType,
    TimeEventType,
)
from hr_time.models.base import TimeTenantModel


class HrTimeEventSource(TimeTenantModel):
    """事件来源（总册 §52）：不同来源不同信任级别。"""

    source_type = models.CharField(
        max_length=32, choices=TimeEventSourceType.choices, verbose_name=_("来源类型")
    )
    provider = models.CharField(
        max_length=64, blank=True, default="", verbose_name=_("提供方")
    )
    device_ref = models.CharField(
        max_length=128, blank=True, default="", verbose_name=_("设备引用")
    )
    trust_level = models.PositiveSmallIntegerField(
        default=1, verbose_name=_("信任级别（1-5，5 最高）")
    )
    signature_required = models.BooleanField(
        default=False, verbose_name=_("要求签名")
    )
    geofence_required = models.BooleanField(
        default=False, verbose_name=_("要求地理围栏")
    )
    active = models.BooleanField(default=True, verbose_name=_("启用"))

    class Meta:
        verbose_name = _("Time Event Source")
        verbose_name_plural = _("Time Event Sources")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "source_type", "provider", "device_ref"],
                name="uniq_hr11_eventsrc",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.source_type}/{self.provider}"


class HrAttendanceDevice(TimeTenantModel):
    """设备注册（总册 §53）。密钥只存 secret_ref，不进明文。"""

    provider = models.CharField(max_length=64, verbose_name=_("提供方"))
    external_device_id = models.CharField(
        max_length=128, verbose_name=_("设备外部 id")
    )
    name = models.CharField(max_length=128, verbose_name=_("设备名"))
    location_id = models.BigIntegerField(null=True, blank=True)
    timezone = models.CharField(
        max_length=64, default="Asia/Shanghai", verbose_name=_("设备时区")
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("ACTIVE", _("在线")),
            ("INACTIVE", _("停用")),
            ("OFFLINE", _("离线")),
        ],
        default="ACTIVE",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    secret_ref = models.CharField(
        max_length=128, blank=True, default="", verbose_name=_("密钥引用（Secret Manager）")
    )
    capabilities = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = _("Attendance Device")
        verbose_name_plural = _("Attendance Devices")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "provider", "external_device_id"],
                name="uniq_hr11_device_ext",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.name} ({self.provider})"


class AppendOnlyQuerySet(models.QuerySet):
    """append-only 事件账本的 queryset 保护：禁止 bulk update/delete（防绕过模型 save guard）。"""

    def update(self, *args, **kwargs):
        raise ValidationError(_("原始事件 append-only，禁止 bulk update"))

    def delete(self, *args, **kwargs):
        raise ValidationError(_("原始事件 append-only，禁止 bulk delete"))


class AppendOnlyManager(models.Manager):
    def get_queryset(self):
        return AppendOnlyQuerySet(self.model, using=self._db)


class HrRawTimeEvent(TimeTenantModel):
    """
    不可变事件账本（总册 §51）。

    append-only 保证（模型层 + queryset 层双保险）：
    - delete() / queryset.delete() 一律拒绝（raise ValidationError）；
    - save() / queryset.update() 对已存在行：关键字段（event 事实）不可变更；
    - 幂等：(tenant_id, source, dedupe_key) 唯一；
    - 时间语义：event_at_utc + event_timezone + local_event_at。
    """

    objects = AppendOnlyManager()

    IMMUTABLE_FIELDS = frozenset(
        {
            "tenant_id",
            "staff_master_id",
            "event_type",
            "event_at_utc",
            "event_timezone",
            "local_event_at",
            "source",
            "source_event_id",
            "dedupe_key",
            "device",
            "location_ref",
            "raw_payload_hash",
            "trust_level",
        }
    )

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    event_type = models.CharField(
        max_length=16, choices=TimeEventType.choices, verbose_name=_("事件类型")
    )
    event_at_utc = models.DateTimeField(verbose_name=_("事件时间（UTC）"))
    event_timezone = models.CharField(
        max_length=64, default="Asia/Shanghai", verbose_name=_("事件时区")
    )
    local_event_at = models.DateTimeField(verbose_name=_("事件时间（本地）"))
    source = models.ForeignKey(
        HrTimeEventSource, on_delete=models.PROTECT, related_name="events"
    )
    source_event_id = models.CharField(
        max_length=128, blank=True, default="", verbose_name=_("来源事件 id")
    )
    dedupe_key = models.CharField(max_length=255, verbose_name=_("幂等键"))
    device = models.ForeignKey(
        HrAttendanceDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
    )
    location_ref = models.CharField(
        max_length=128, blank=True, default="", verbose_name=_("位置引用")
    )
    raw_payload_hash = models.CharField(
        max_length=64, verbose_name=_("原始载荷哈希")
    )
    trust_level = models.PositiveSmallIntegerField(default=1, verbose_name=_("信任级别"))
    ingest_status = models.CharField(
        max_length=32,
        choices=TimeEventIngestStatus.choices,
        default=TimeEventIngestStatus.RECEIVED,
    )

    class Meta:
        verbose_name = _("Raw Time Event")
        verbose_name_plural = _("Raw Time Events")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "source", "dedupe_key"],
                name="uniq_hr11_event_dedupe",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "event_at_utc"],
                name="hr11_event_ten_staff_at",
            ),
            models.Index(
                fields=["tenant_id", "source", "event_at_utc"],
                name="hr11_event_ten_src_at",
            ),
        ]

    def save(self, *args, **kwargs):
        """immutable：已存在事件的关键字段不可变更。"""
        if self.pk:
            old = HrRawTimeEvent.objects.get(pk=self.pk)
            changed = [
                f
                for f in self.IMMUTABLE_FIELDS
                if getattr(old, f, None) != getattr(self, f, None)
            ]
            if changed:
                raise ValidationError(
                    _("原始事件不可变，禁止修改字段: %(fields)s；更正请走 Correction Case")
                    % {"fields": ", ".join(sorted(changed))}
                )
            allowed_transitions = {
                TimeEventIngestStatus.RECEIVED: {
                    TimeEventIngestStatus.RECEIVED,
                    TimeEventIngestStatus.VALIDATED,
                    TimeEventIngestStatus.PERSON_UNMAPPED,
                    TimeEventIngestStatus.REJECTED,
                    TimeEventIngestStatus.STAGED,
                },
                TimeEventIngestStatus.STAGED: {
                    TimeEventIngestStatus.STAGED,
                    TimeEventIngestStatus.VALIDATED,
                    TimeEventIngestStatus.REJECTED,
                },
            }
            if self.ingest_status not in allowed_transitions.get(
                old.ingest_status, {old.ingest_status}
            ):
                raise ValidationError(_("原始事件处理状态转换非法"))
        if self.source_id and self.source.tenant_id != self.tenant_id:
            raise ValidationError(_("原始事件与来源必须属于同一租户"))
        if self.device_id and self.device.tenant_id != self.tenant_id:
            raise ValidationError(_("原始事件与设备必须属于同一租户"))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("原始事件 append-only，禁止删除"))

    def __str__(self):
        return f"[{self.tenant_id}] {self.staff_master_id} {self.event_type} {self.event_at_utc}"


class HrTimeEventPair(TimeTenantModel):
    """事件配对（总册 §59）。"""

    in_event = models.ForeignKey(
        HrRawTimeEvent, on_delete=models.PROTECT, related_name="+"
    )
    out_event = models.ForeignKey(
        HrRawTimeEvent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    pairing_status = models.CharField(
        max_length=32,
        choices=PairingStatus.choices,
        default=PairingStatus.OPEN,
    )
    pairing_rule_version = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("配对规则版本")
    )
    shift_business_date = models.DateField(verbose_name=_("班次业务日期"))
    duration_minutes = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("时长（分钟）")
    )
    anomaly_codes = models.JSONField(default=list, blank=True)

    def clean(self):
        super().clean()
        # 防跨租户/跨人员配对（S4 生产级校验）
        if self.in_event.tenant_id != self.tenant_id:
            raise ValidationError(_("配对 in_event 不属于当前租户"))
        if self.out_event_id and self.out_event.tenant_id != self.tenant_id:
            raise ValidationError(_("配对 out_event 不属于当前租户"))
        if self.out_event_id and self.out_event.staff_master_id != self.in_event.staff_master_id:
            raise ValidationError(_("配对 in/out 事件必须属于同一人员"))

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Time Event Pair")
        verbose_name_plural = _("Time Event Pairs")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "in_event"], name="uniq_hr11_pair_inevent"
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "pairing_status", "shift_business_date"],
                name="hr11_pair_ten_status_date",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] in={self.in_event_id} {self.pairing_status}"
