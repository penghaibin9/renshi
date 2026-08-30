"""
hr_time/models/leave.py

S7 请假休假基础（总册 §83-91、§191）。

- HrLeaveType：假别目录（category/unit/paid_classification，具体法律适用由 PolicyVersion 决定）
- HrLeavePolicyPack / HrLeavePolicyVersion：假别政策（PUBLISHED 后 immutable）
- HrLeaveEnrollment：入保（eligibility snapshot，入职/转岗后重评）
- HrLeaveAccount / HrLeaveLedgerEntry：假期账户 + Ledger（禁止只存 running total）
- HrSchoolBreakFact：寒暑假事实（年休假交互）

铁律（总册 §90-91、§199）：
- 年休假余额禁止 `annual_leave_balance = 10` 单值；必须 Entitlement→Ledger 链；
- 教师有寒暑假 ≠ 无年休假（禁止 `teacher=True → annual_leave=0`）；
- 假别规则版本化，禁止 `if leave_type == ...` 硬编码；
- 余额=ledger 求和；调整必须经 Adjust Case（S8）。
"""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_time.enums import (
    LeaveCategory,
    LeaveLedgerEntryType,
    LeaveUnit,
    PolicyStatus,
)
from hr_time.models.base import AppendOnlyLedgerModel, TimeTenantModel
from hr_time.models.policy import VersionManager


class HrLeaveType(TimeTenantModel):
    """假别目录（§83）。"""

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    category = models.CharField(
        max_length=32, choices=LeaveCategory.choices, default=LeaveCategory.OTHER
    )
    unit = models.CharField(
        max_length=16, choices=LeaveUnit.choices, default=LeaveUnit.DAYS
    )
    paid_classification = models.CharField(
        max_length=16,
        choices=[
            ("PAID", _("带薪")),
            ("UNPAID", _("无薪")),
            ("POLICY_DEPENDENT", _("依政策")),
        ],
        default="POLICY_DEPENDENT",
    )
    requires_plan = models.BooleanField(default=True, verbose_name=_("需要额度账户"))
    requires_evidence = models.BooleanField(default=False, verbose_name=_("需要证明"))
    sensitive_reason = models.BooleanField(
        default=False, verbose_name=_("敏感原因（病假等）")
    )
    active = models.BooleanField(default=True, verbose_name=_("启用"))

    class Meta:
        verbose_name = _("Leave Type")
        verbose_name_plural = _("Leave Types")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_lt_code"
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.name}"


class HrLeavePolicyPack(TimeTenantModel):
    """假别政策包（§84）：一个学校可有多个（事业编/合同制/外聘/教师/行政）。"""

    code = models.CharField(max_length=64, verbose_name=_("Code"))
    name = models.CharField(max_length=128, verbose_name=_("Name"))
    jurisdiction = models.CharField(max_length=64, blank=True, default="")
    worker_scope = models.CharField(max_length=128, blank=True, default="")
    current_version_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("Leave Policy Pack")
        verbose_name_plural = _("Leave Policy Packs")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"], name="uniq_hr11_lppack_code"
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.code} - {self.name}"


class HrLeavePolicyVersion(TimeTenantModel):
    """假别政策版本（§85）。PUBLISHED 后 immutable。"""

    IMMUTABLE_AFTER_PUBLISH_FIELDS = frozenset(
        {
            "leave_type",
            "entitlement_mode",
            "eligibility_rule",
            "grant_accrual_rule",
            "carry_forward_rule",
            "expiry_rule",
            "reservation_rule",
            "evidence_rule",
            "approval_rule",
            "interaction_rules",
            "effective_from",
            "effective_to",
            "version_no",
        }
    )

    leave_policy_pack = models.ForeignKey(
        HrLeavePolicyPack, on_delete=models.PROTECT, related_name="versions"
    )
    objects = VersionManager()
    leave_type = models.ForeignKey(
        HrLeaveType, on_delete=models.PROTECT, related_name="policy_versions"
    )
    version_no = models.PositiveIntegerField(verbose_name=_("版本号"))
    status = models.CharField(
        max_length=16, choices=PolicyStatus.choices, default=PolicyStatus.DRAFT
    )
    entitlement_mode = models.CharField(
        max_length=32,
        choices=[
            ("GRANT", _("直接授予")),
            ("ACCRUAL", _("累积")),
            ("SERVICE_YEARS", _("按服务年限")),
            ("LEGAL_TIER", _("法定档位")),
        ],
        default="GRANT",
    )
    eligibility_rule = models.JSONField(default=dict, blank=True)
    grant_accrual_rule = models.JSONField(default=dict, blank=True)
    carry_forward_rule = models.JSONField(default=dict, blank=True)
    expiry_rule = models.JSONField(default=dict, blank=True)
    reservation_rule = models.JSONField(default=dict, blank=True)
    evidence_rule = models.JSONField(default=dict, blank=True)
    approval_rule = models.JSONField(default=dict, blank=True)
    interaction_rules = models.JSONField(default=dict, blank=True)
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
    content_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        verbose_name = _("Leave Policy Version")
        verbose_name_plural = _("Leave Policy Versions")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "leave_policy_pack", "version_no"],
                name="uniq_hr11_lpver_no",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "leave_policy_pack", "status"],
                name="hr11_lpver_ten_pack_status",
            ),
        ]

    def save(self, *args, **kwargs):
        """immutable guard：已 PUBLISHED 版本不可修改关键内容。"""
        old = None
        if self.pk:
            old = HrLeavePolicyVersion.objects.get(pk=self.pk)
            if old.status == PolicyStatus.RETIRED:
                raise ValidationError(_("已退役假别政策不可修改"))
            if old.status == PolicyStatus.PUBLISHED:
                if self.status != PolicyStatus.RETIRED:
                    raise ValidationError(_("已发布假别政策只能退役（RETIRED）"))
                changed = [
                    f
                    for f in self.IMMUTABLE_AFTER_PUBLISH_FIELDS
                    if getattr(old, f, None) != getattr(self, f, None)
                ]
                if changed:
                    raise ValidationError(
                        _("已发布假别政策不可修改字段: %(fields)s；变更请创建新版本")
                        % {"fields": ", ".join(sorted(changed))}
                    )
                self.content_hash = old.content_hash
        if self.leave_policy_pack_id and self.leave_policy_pack.tenant_id != self.tenant_id:
            raise ValidationError(_("假别政策版本与政策包必须属于同一租户"))
        if self.leave_type_id and self.leave_type.tenant_id != self.tenant_id:
            raise ValidationError(_("假别政策版本与假别必须属于同一租户"))
        if self.status == PolicyStatus.PUBLISHED and (
            old is None or old.status != PolicyStatus.PUBLISHED
        ):
            payload = {
                "tenantId": self.tenant_id,
                "leavePolicyPackId": self.leave_policy_pack_id,
                "leaveTypeId": self.leave_type_id,
                "versionNo": self.version_no,
                "entitlementMode": self.entitlement_mode,
                "eligibilityRule": self.eligibility_rule,
                "grantAccrualRule": self.grant_accrual_rule,
                "carryForwardRule": self.carry_forward_rule,
                "expiryRule": self.expiry_rule,
                "reservationRule": self.reservation_rule,
                "evidenceRule": self.evidence_rule,
                "approvalRule": self.approval_rule,
                "interactionRules": self.interaction_rules,
                "effectiveFrom": self.effective_from.isoformat(),
                "effectiveTo": self.effective_to.isoformat() if self.effective_to else None,
            }
            self.content_hash = hashlib.sha256(
                json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            self.published_at = self.published_at or timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] {self.leave_policy_pack.code}/{self.leave_type.code} v{self.version_no}"


class HrLeaveEnrollment(TimeTenantModel):
    """假期入保（§86）。入职/转岗/类别变化后重新评估，不直接重建历史余额。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    employment_relationship_id = models.BigIntegerField(null=True, blank=True)
    leave_policy_version = models.ForeignKey(
        HrLeavePolicyVersion, on_delete=models.PROTECT, related_name="enrollments"
    )
    enrolled_from = models.DateField(verbose_name=_("入保开始"))
    enrolled_to = models.DateField(null=True, blank=True, verbose_name=_("入保结束"))
    eligibility_snapshot = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=32, default="MANUAL", verbose_name=_("来源"))

    class Meta:
        verbose_name = _("Leave Enrollment")
        verbose_name_plural = _("Leave Enrollments")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "enrolled_from"],
                name="hr11_enroll_ten_staff_from",
            ),
        ]

    def clean(self):
        super().clean()
        if self.enrolled_to and self.enrolled_to < self.enrolled_from:
            raise ValidationError(_("入保结束日期早于开始日期"))

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.enrolled_from}"


class HrLeaveAccount(TimeTenantModel):
    """假期账户（§87）。余额来自 ledger 求和，不把 balance 当唯一事实。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    leave_type = models.ForeignKey(
        HrLeaveType, on_delete=models.PROTECT, related_name="accounts"
    )
    policy_version = models.ForeignKey(
        HrLeavePolicyVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    account_year = models.PositiveIntegerField(verbose_name=_("账户年度"))
    status = models.CharField(
        max_length=16,
        choices=[
            ("ACTIVE", _("生效")),
            ("CLOSED", _("已结清")),
        ],
        default="ACTIVE",
    )

    class Meta:
        verbose_name = _("Leave Account")
        verbose_name_plural = _("Leave Accounts")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "staff_master_id", "leave_type", "account_year"],
                name="uniq_hr11_leave_acct",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.leave_type.code} {self.account_year}"


class HrLeaveLedgerEntry(AppendOnlyLedgerModel):
    """假期 Ledger（§88）。entry_type 冻结（GRANT/ACCRUAL/RESERVE/...）。"""

    account = models.ForeignKey(
        HrLeaveAccount, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    entry_type = models.CharField(
        max_length=32, choices=LeaveLedgerEntryType.choices
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2, verbose_name=_("数量"))
    unit = models.CharField(
        max_length=16, choices=LeaveUnit.choices, default=LeaveUnit.DAYS
    )
    effective_date = models.DateField(verbose_name=_("生效日"))
    source_type = models.CharField(max_length=32, verbose_name=_("来源类型"))
    source_id = models.CharField(max_length=64, blank=True, default="")
    reversal_of = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals"
    )
    expires_at = models.DateField(null=True, blank=True, verbose_name=_("过期日"))
    balance_after = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, verbose_name=_("变动后余额")
    )

    class Meta:
        verbose_name = _("Leave Ledger Entry")
        verbose_name_plural = _("Leave Ledger Entries")
        indexes = [
            models.Index(
                fields=["tenant_id", "account", "effective_date"],
                name="hr11_ledger_entry_date",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "reversal_of"],
                name="uniq_hr11_leave_reversal",
            ),
        ]

    def clean(self):
        super().clean()
        if self.amount == 0:
            raise ValidationError(_("ledger 条目 amount 不能为 0"))
        if self.account_id and self.account.tenant_id != self.tenant_id:
            raise ValidationError(_("假期账本与账户必须属于同一租户"))
        if self.reversal_of_id:
            reversal = self.reversal_of
            if reversal.tenant_id != self.tenant_id or reversal.account_id != self.account_id:
                raise ValidationError(_("冲正记录与原记录必须属于同一租户、同一账户"))
            if self.entry_type != LeaveLedgerEntryType.RESERVATION_RELEASE:
                raise ValidationError(_("当前仅预占释放记录可引用 reversal_of"))
            if reversal.entry_type != LeaveLedgerEntryType.RESERVE:
                raise ValidationError(_("预占释放必须引用 RESERVE 记录"))
            if self.amount != reversal.amount or self.unit != reversal.unit:
                raise ValidationError(_("预占释放数量与单位必须和 RESERVE 完全一致"))

    def __str__(self):
        return f"[{self.tenant_id}] acct={self.account_id} {self.entry_type} {self.amount}"


class HrSchoolBreakFact(TimeTenantModel):
    """寒暑假事实（§91）。年休假 evaluator 读取 verified facts。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    school_year = models.CharField(max_length=16, verbose_name=_("学年"))
    break_type = models.CharField(
        max_length=16,
        choices=[
            ("WINTER", _("寒假")),
            ("SUMMER", _("暑假")),
        ],
    )
    scheduled_days = models.PositiveIntegerField(verbose_name=_("计划假期天数"))
    actually_released_days = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_("实际放假天数")
    )
    worked_during_break_days = models.PositiveIntegerField(
        default=0, verbose_name=_("假期期间工作天数")
    )
    source = models.CharField(max_length=32, default="MANUAL", verbose_name=_("来源"))
    verified = models.BooleanField(default=False, verbose_name=_("已核验"))

    class Meta:
        verbose_name = _("School Break Fact")
        verbose_name_plural = _("School Break Facts")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "staff_master_id", "school_year", "break_type"],
                name="uniq_hr11_break_fact",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.school_year} {self.break_type}"
