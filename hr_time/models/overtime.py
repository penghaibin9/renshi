"""
hr_time/models/overtime.py

S6 异常/补卡/加班（总册 §71-79、§190）。

- HrAttendanceException：异常目录（13 类，code 稳定）
- HrAttendanceCorrectionCase：补卡/更正 case（月结前/后不同流程）
- HrTimeSourceIncident：设备故障（影响期间不批量判缺勤）
- HrOvertimeRequest：加班申请（APPROVED 只表示批准可以加班，≠实际工时）
- HrOvertimeFact：加班事实（actual/eligible/settlement_mode）
- HrCompTimeAccount / HrCompTimeLedger：调休独立账户（来源=verified OT fact）

铁律（总册 §76-79、§199）：
- approved overtime 不自动等于实际加班时长；
- 加班评估 = approved window ∩ actual worked ∩ eligible policy - unpaid breaks（§78）；
- 调休与年休假分账；加班事实直接发钱不经过 HR15 规则；
- 补卡不 UPDATE 原始事件（走 Correction Case → Fact V2）。
"""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_time.enums import ExceptionCode, OvertimeSettlementMode
from hr_time.models.attendance import HrAttendanceDayFact
from hr_time.models.base import AppendOnlyLedgerModel, TimeTenantModel


class HrAttendanceException(TimeTenantModel):
    """考勤异常（§73：目录 code 稳定，学校可扩展）。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    business_date = models.DateField(verbose_name=_("班次业务日期"))
    exception_code = models.CharField(
        max_length=32, choices=ExceptionCode.choices, verbose_name=_("异常码")
    )
    source_fact = models.ForeignKey(
        HrAttendanceDayFact,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="exceptions",
    )
    evidence = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=[
            ("OPEN", _("待处理")),
            ("REVIEWING", _("复核中")),
            ("RESOLVED", _("已解决")),
            ("DISMISSED", _("已排除")),
        ],
        default="OPEN",
    )
    resolved_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("Attendance Exception")
        verbose_name_plural = _("Attendance Exceptions")
        indexes = [
            models.Index(
                fields=["tenant_id", "status", "business_date"],
                name="hr11_exc_ten_status_date",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.exception_code} {self.status}"


class HrAttendanceCorrectionCase(TimeTenantModel):
    """考勤更正 case（§71-72）。禁止原地覆盖事实。"""

    REASON_CODES = [
        ("MISSING_PUNCH", _("漏卡")),
        ("WRONG_PUNCH", _("错卡")),
        ("DEVICE_OUTAGE", _("设备故障")),
        ("OFFICIAL_DUTY", _("公务/外勤")),
        ("MIGRATION", _("历史迁移")),
        ("AUTHORIZED_CORRECTION", _("授权更正")),
    ]
    STATUS = [
        ("SUBMITTED", _("已提交")),
        ("UNDER_REVIEW", _("复核中")),
        ("APPROVED", _("已批准")),
        ("REJECTED", _("已拒绝")),
    ]

    target_fact = models.ForeignKey(
        HrAttendanceDayFact, on_delete=models.PROTECT, related_name="corrections"
    )
    requested_change_json = models.JSONField(default=dict, blank=True)
    reason_code = models.CharField(max_length=32, choices=REASON_CODES)
    evidence_ids = models.JSONField(default=list, blank=True)
    requester = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=32, choices=STATUS, default="SUBMITTED")
    approval_snapshot = models.JSONField(default=dict, blank=True)
    resulting_fact_version_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = _("Attendance Correction Case")
        verbose_name_plural = _("Attendance Correction Cases")

    def __str__(self):
        return f"[{self.tenant_id}] case={self.pk} {self.reason_code} {self.status}"


class HrTimeSourceIncident(TimeTenantModel):
    """设备/来源故障（§74）。影响期间不自动批量判缺勤。"""

    SEVERITY = [
        ("LOW", _("低")),
        ("MEDIUM", _("中")),
        ("HIGH", _("高")),
        ("CRITICAL", _("严重")),
    ]

    source_ref = models.CharField(max_length=128, verbose_name=_("来源/设备引用"))
    start_at = models.DateTimeField(verbose_name=_("开始时间"))
    end_at = models.DateTimeField(null=True, blank=True, verbose_name=_("结束时间"))
    affected_scope = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=16, choices=SEVERITY, default="MEDIUM")
    reconciliation_status = models.CharField(
        max_length=16,
        choices=[
            ("OPEN", _("待对账")),
            ("RECONCILING", _("对账中")),
            ("RECONCILED", _("已对账")),
        ],
        default="OPEN",
    )

    class Meta:
        verbose_name = _("Time Source Incident")
        verbose_name_plural = _("Time Source Incidents")
        indexes = [
            models.Index(
                fields=["tenant_id", "severity", "start_at"],
                name="hr11_inc_ten_sev_start",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.source_ref} {self.severity}"


class HrOvertimeRequest(TimeTenantModel):
    """加班申请（§76）。APPROVED 只是批准可以加班，≠实际工时。"""

    STATUS = [
        ("DRAFT", _("草稿")),
        ("SUBMITTED", _("已提交")),
        ("APPROVED", _("已批准")),
        ("REJECTED", _("已拒绝")),
        ("CANCELLED", _("已取消")),
    ]

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    assignment_id = models.BigIntegerField(null=True, blank=True)
    requested_start_at = models.DateTimeField(verbose_name=_("申请开始"))
    requested_end_at = models.DateTimeField(verbose_name=_("申请结束"))
    reason = models.CharField(max_length=255, verbose_name=_("原因"))
    overtime_type = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("加班类型")
    )
    planned_minutes = models.PositiveIntegerField(verbose_name=_("计划时长（分钟）"))
    approver = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=16, choices=STATUS, default="DRAFT")
    approval_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Overtime Request")
        verbose_name_plural = _("Overtime Requests")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "status"],
                name="hr11_otreq_ten_staff_status",
            ),
        ]

    def clean(self):
        super().clean()
        if self.requested_end_at and self.requested_start_at:
            if self.requested_end_at <= self.requested_start_at:
                raise ValidationError(_("加班申请结束时间必须晚于开始时间"))

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.status}"


class HrOvertimeFact(TimeTenantModel):
    """加班事实（§77）。可验证的候选/已核验加班。"""

    IMMUTABLE_IDENTITY_FIELDS = (
        "tenant_id",
        "request_id",
        "staff_master_id",
        "actual_start_at",
        "actual_end_at",
        "actual_minutes",
        "eligible_minutes",
        "policy_version_id",
    )

    request = models.ForeignKey(
        HrOvertimeRequest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="facts",
    )
    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    actual_start_at = models.DateTimeField(verbose_name=_("实际开始"))
    actual_end_at = models.DateTimeField(verbose_name=_("实际结束"))
    actual_minutes = models.PositiveIntegerField(verbose_name=_("实际时长（分钟）"))
    eligible_minutes = models.PositiveIntegerField(verbose_name=_("可结算时长（分钟）"))
    policy_version_id = models.BigIntegerField(null=True, blank=True)
    evidence_source = models.CharField(max_length=64, blank=True, default="")
    verification_status = models.CharField(
        max_length=16,
        choices=[
            ("CANDIDATE", _("候选")),
            ("VERIFIED", _("已核验")),
            ("REJECTED", _("已驳回")),
        ],
        default="CANDIDATE",
    )
    settlement_mode = models.CharField(
        max_length=32,
        choices=OvertimeSettlementMode.choices,
        default=OvertimeSettlementMode.POLICY_DEPENDENT,
    )
    verification_receipt_json = models.JSONField(default=dict, blank=True)
    verification_receipt_hash = models.CharField(max_length=64, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        "horilla_auth.HorillaUser",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Overtime Fact")
        verbose_name_plural = _("Overtime Facts")
        indexes = [
            models.Index(
                fields=["tenant_id", "staff_master_id", "verification_status"],
                name="hr11_otfact_ten_staff_ver",
            ),
        ]

    def clean(self):
        super().clean()
        if self.eligible_minutes > self.actual_minutes:
            raise ValidationError(_("可结算时长不能大于实际时长"))
        if self.request_id:
            if self.request.tenant_id != self.tenant_id:
                raise ValidationError(_("加班事实与申请必须属于同一租户"))
            if self.request.staff_master_id != self.staff_master_id:
                raise ValidationError(_("加班事实与申请必须属于同一人员"))
        if self.verification_status == "VERIFIED":
            if self.settlement_mode == OvertimeSettlementMode.POLICY_DEPENDENT:
                raise ValidationError(_("已核验加班必须冻结明确结算方式"))
            if not self.verified_at or not self.verified_by_id:
                raise ValidationError(_("已核验加班必须记录核验人和核验时间"))
            if not self.verify_receipt():
                raise ValidationError(_("加班核验回执哈希无效"))

    def verification_payload(self):
        return {
            "tenantId": int(self.tenant_id),
            "overtimeFactId": int(self.id),
            "staffMasterId": int(self.staff_master_id),
            "requestId": int(self.request_id) if self.request_id else None,
            "actualStartAt": self.actual_start_at.isoformat(),
            "actualEndAt": self.actual_end_at.isoformat(),
            "actualMinutes": int(self.actual_minutes),
            "eligibleMinutes": int(self.eligible_minutes),
            "policyVersionId": int(self.policy_version_id) if self.policy_version_id else None,
            "evidenceSource": self.evidence_source,
            "settlementMode": self.settlement_mode,
            "verifiedAt": self.verified_at.isoformat() if self.verified_at else None,
            "verifiedBy": int(self.verified_by_id) if self.verified_by_id else None,
            "receipt": self.verification_receipt_json or {},
        }

    def compute_receipt_hash(self):
        return hashlib.sha256(
            json.dumps(
                self.verification_payload(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def verify_receipt(self):
        return bool(self.verification_receipt_hash) and (
            self.verification_receipt_hash == self.compute_receipt_hash()
        )

    def save(self, *args, **kwargs):
        if self.pk:
            old = HrOvertimeFact._base_manager.filter(pk=self.pk).first()
            if old and any(
                getattr(old, field) != getattr(self, field)
                for field in self.IMMUTABLE_IDENTITY_FIELDS
            ):
                raise ValidationError(_("加班事实身份字段不可修改；更正必须追加新事实"))
            if old and old.verification_status in {"VERIFIED", "REJECTED"}:
                raise ValidationError(_("终局加班事实不可修改；更正必须追加新事实"))
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.verification_status in {"VERIFIED", "REJECTED"}:
            raise ValidationError(_("终局加班事实不可删除"))
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.actual_minutes}min {self.verification_status}"


class HrCompTimeAccount(TimeTenantModel):
    """调休账户（§79）。与年休假分账。"""

    staff_master_id = models.BigIntegerField(verbose_name=_("HR03 人员 id"))
    account_year = models.PositiveIntegerField(verbose_name=_("年度"))
    status = models.CharField(
        max_length=16,
        choices=[
            ("ACTIVE", _("生效")),
            ("CLOSED", _("已结清")),
        ],
        default="ACTIVE",
    )

    class Meta:
        verbose_name = _("Comp Time Account")
        verbose_name_plural = _("Comp Time Accounts")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "staff_master_id", "account_year"],
                name="uniq_hr11_comptime_acct",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] staff={self.staff_master_id} {self.account_year}"


class HrCompTimeLedger(AppendOnlyLedgerModel):
    """调休 Ledger（§79）。来源必须是 verified overtime fact。"""

    account = models.ForeignKey(
        HrCompTimeAccount, on_delete=models.CASCADE, related_name="entries"
    )
    entry_type = models.CharField(
        max_length=16,
        choices=[
            ("CREDIT", _("入账")),
            ("DEBIT", _("使用")),
            ("REVERSAL", _("冲正")),
            ("EXPIRE", _("过期")),
        ],
    )
    minutes = models.PositiveIntegerField(verbose_name=_("分钟"))
    source_fact = models.ForeignKey(
        HrOvertimeFact,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    effective_date = models.DateField(verbose_name=_("生效日"))
    balance_after = models.IntegerField(default=0, verbose_name=_("变动后余额（分钟）"))
    reversal_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = _("Comp Time Ledger")
        verbose_name_plural = _("Comp Time Ledgers")
        indexes = [
            models.Index(
                fields=["tenant_id", "account", "effective_date"],
                name="hr11_comptime_ledger_date",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "source_fact", "entry_type"],
                name="uniq_hr11_comp_fact_entry",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] acct={self.account_id} {self.entry_type} {self.minutes}min"

    def clean(self):
        super().clean()
        if self.account_id and self.account.tenant_id != self.tenant_id:
            raise ValidationError(_("调休账本与账户必须属于同一租户"))
        if self.source_fact_id:
            if self.source_fact.tenant_id != self.tenant_id:
                raise ValidationError(_("调休来源事实与账户必须属于同一租户"))
            if self.source_fact.staff_master_id != self.account.staff_master_id:
                raise ValidationError(_("调休来源事实与账户必须属于同一人员"))
            if self.source_fact.verification_status != "VERIFIED":
                raise ValidationError(_("调休入账只能引用已核验加班事实"))
            if not self.source_fact.verify_receipt():
                raise ValidationError(_("调休入账只能引用可信核验回执"))
        if self.reversal_of_id:
            reversal = self.reversal_of
            if reversal.tenant_id != self.tenant_id or reversal.account_id != self.account_id:
                raise ValidationError(_("调休冲正必须引用同租户、同账户原记录"))
