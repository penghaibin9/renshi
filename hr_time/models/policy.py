"""
hr_time/models/policy.py

S2 工作制度与规则版本（总册 §26-28、§186）。

- HrTimeRecordingProfile：记录方式模板（行为定义，具体适用由 PolicyVersion eligibility 决定，§24）；
- HrTimePolicyPack：规则包（学校可扩展 policy_family）；
- HrTimePolicyVersion：规则版本，PUBLISHED 后 immutable（§27）。

铁律（总册 §199）：
- 假别规则/宽限/加班资格等一律版本化，禁止在 Python `if ...` 硬编码；
- 发布后只能新版本，不能改已发布版本；
- 规则变更不得污染历史（as-of 引用当时版本）。
"""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_time.enums import PolicyStatus, RecordingMethod
from hr_time.models.base import TimeTenantModel

# 政策家族（总册 §26，学校可扩展）
POLICY_FAMILY_CHOICES = [
    ("ADMIN_FIXED", _("行政固定班")),
    ("TEACHER_FLEX", _("教师弹性")),
    ("LAB_SHIFT", _("实验室轮班")),
    ("SECURITY_ROTATION", _("安保轮转")),
    ("COUNSELOR_DUTY", _("辅导员值班")),
    ("EXTERNAL_SERVICE", _("外聘服务")),
    ("OTHER", _("其他")),
]

POLICY_PACK_STATUS = [
    ("ACTIVE", _("生效")),
    ("INACTIVE", _("停用")),
]


def _stable_dumps(data) -> str:
    """稳定 JSON 序列化（key 排序）用于 content_hash。"""
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class VersionQuerySet(models.QuerySet):
    """版本对象的 queryset 保护：bulk update/delete 一律拒绝，编辑必须逐行 save() 走 immutable guard。"""

    def update(self, *args, **kwargs):
        raise ValidationError(_("版本对象禁止 bulk update；请逐行保存以触发 immutable guard"))

    def delete(self, *args, **kwargs):
        raise ValidationError(_("版本对象禁止 bulk delete"))


class VersionManager(models.Manager):
    def get_queryset(self):
        return VersionQuerySet(self.model, using=self._db)


class HrTimeRecordingProfile(TimeTenantModel):
    """
    记录方式模板（总册 §24）。

    只定义行为模板；具体适用由 PolicyVersion 的 eligibility 决定。
    禁止 `if employee_type == "teacher": no attendance`。
    """

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    method = models.CharField(
        max_length=32, choices=RecordingMethod.choices, verbose_name=_("记录方式")
    )
    requires_punch = models.BooleanField(default=True, verbose_name=_("要求打卡"))
    requires_timesheet = models.BooleanField(default=False, verbose_name=_("要求工时申报"))
    requires_daily_presence = models.BooleanField(default=True, verbose_name=_("要求日考勤"))
    overtime_recording_mode = models.CharField(
        max_length=32, default="ON_REQUEST", verbose_name=_("加班记录方式")
    )
    absence_recording_mode = models.CharField(
        max_length=32, default="ON_EXCEPTION", verbose_name=_("缺勤记录方式")
    )
    effective_from = models.DateField(verbose_name=_("生效日"))
    effective_to = models.DateField(null=True, blank=True, verbose_name=_("失效日"))
    version = models.PositiveIntegerField(default=1, verbose_name=_("版本号"))

    class Meta:
        verbose_name = _("Time Recording Profile")
        verbose_name_plural = _("Time Recording Profiles")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_rec_profile_code"
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.get_method_display()}"


class HrTimePolicyPack(TimeTenantModel):
    """规则包（总册 §26）。定义逻辑身份，不直接修改历史版本内容。"""

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    policy_family = models.CharField(
        max_length=32, choices=POLICY_FAMILY_CHOICES, default="OTHER"
    )
    status = models.CharField(
        max_length=16, choices=POLICY_PACK_STATUS, default="ACTIVE"
    )
    current_version_id = models.BigIntegerField(
        null=True, blank=True, verbose_name=_("当前版本 id")
    )
    effective_scope = models.JSONField(
        default=dict, blank=True, verbose_name=_("生效范围")
    )

    class Meta:
        verbose_name = _("Time Policy Pack")
        verbose_name_plural = _("Time Policy Packs")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_ppack_code"
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.name}"


class HrTimePolicyVersion(TimeTenantModel):
    """
    规则版本（总册 §27）。

    发布（PUBLISHED）后 immutable：
    - save() 拒绝修改已 PUBLISHED 版本的关键字段；
    - content_hash 冻结版本内容，供 as-of 引用与审计比对；
    - 规则变更只能新版本。
    """

    IMMUTABLE_AFTER_PUBLISH_FIELDS = frozenset(
        {
            "recording_profile_id",
            "work_calendar_policy",
            "schedule_policy",
            "grace_policy_json",
            "rounding_policy_json",
            "overtime_policy_ref",
            "leave_policy_ref",
            "missing_punch_policy",
            "absence_policy",
            "effective_from",
            "effective_to",
            "version_no",
        }
    )

    policy_pack = models.ForeignKey(
        HrTimePolicyPack, on_delete=models.PROTECT, related_name="versions"
    )
    objects = VersionManager()
    version_no = models.PositiveIntegerField(verbose_name=_("版本号"))
    status = models.CharField(
        max_length=16, choices=PolicyStatus.choices, default=PolicyStatus.DRAFT
    )
    recording_profile = models.ForeignKey(
        HrTimeRecordingProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    work_calendar_policy = models.JSONField(default=dict, blank=True)
    schedule_policy = models.JSONField(default=dict, blank=True)
    grace_policy_json = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("宽限政策（late/early grace minutes 等）"),
    )
    rounding_policy_json = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("取整政策（raw 事件永不取整）"),
    )
    overtime_policy_ref = models.JSONField(
        default=dict, blank=True, verbose_name=_("加班政策引用")
    )
    leave_policy_ref = models.JSONField(
        default=dict, blank=True, verbose_name=_("请假政策引用")
    )
    missing_punch_policy = models.JSONField(
        default=dict, blank=True, verbose_name=_("缺卡政策")
    )
    absence_policy = models.JSONField(
        default=dict, blank=True, verbose_name=_("缺勤政策")
    )
    effective_from = models.DateField(verbose_name=_("生效日"))
    effective_to = models.DateField(null=True, blank=True, verbose_name=_("失效日"))
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    content_hash = models.CharField(
        max_length=64, blank=True, editable=False, verbose_name=_("内容哈希")
    )

    class Meta:
        verbose_name = _("Time Policy Version")
        verbose_name_plural = _("Time Policy Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "policy_pack", "version_no"],
                name="uniq_hr11_pver_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "policy_pack", "status"],
                name="hr11_pver_tpack_status",
            ),
        ]

    def content_payload(self) -> dict:
        """参与 content_hash 的内容（不含审计/状态字段）。"""
        return {
            "tenant_id": self.tenant_id,
            "policy_pack": self.policy_pack_id,
            "version_no": self.version_no,
            "recording_profile": self.recording_profile_id,
            "work_calendar_policy": self.work_calendar_policy,
            "schedule_policy": self.schedule_policy,
            "grace_policy_json": self.grace_policy_json,
            "rounding_policy_json": self.rounding_policy_json,
            "overtime_policy_ref": self.overtime_policy_ref,
            "leave_policy_ref": self.leave_policy_ref,
            "missing_punch_policy": self.missing_punch_policy,
            "absence_policy": self.absence_policy,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
        }

    def compute_content_hash(self) -> str:
        return hashlib.sha256(_stable_dumps(self.content_payload()).encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        """immutable guard：已 PUBLISHED 版本不可修改关键内容。"""
        if self.pk:
            try:
                old = HrTimePolicyVersion.objects.get(pk=self.pk)
            except HrTimePolicyVersion.DoesNotExist:
                old = None
            if old is not None and old.status == PolicyStatus.PUBLISHED:
                if old.status != self.status:
                    # 状态变更受控：仅允许 RETIRED（退役），不允许改回 DRAFT
                    if self.status != PolicyStatus.RETIRED:
                        raise ValidationError(
                            _("已发布版本只能退役（RETIRED），不能改回草稿/其他状态")
                        )
                changed_fields = [
                    f
                    for f in self.IMMUTABLE_AFTER_PUBLISH_FIELDS
                    if getattr(old, f, None) != getattr(self, f, None)
                ]
                if changed_fields:
                    raise ValidationError(
                        _("已发布版本不可修改字段: %(fields)s；规则变更请创建新版本")
                        % {"fields": ", ".join(sorted(changed_fields))}
                    )
                # 内容未变则保持原 hash
                self.content_hash = old.content_hash
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] {self.policy_pack.code} v{self.version_no} ({self.status})"
