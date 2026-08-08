"""
hr_recruitment/models/offer.py

HR04-06 录用与人才引进（《04_HR04_总册》§13 + HR05 RecruitToHireMapping）。

HrProposedHire（拟录用）→ HrPublicNotice/HrPublicNoticeEntry（公示）
→ HrNoticeObjection（异议案件）→ HrRecruitmentOffer（Offer）
→ HrRecruitmentHandoff（HANDOFF_TO_HR05，幂等）

硬规则（§13.7 / HR05 契约）：
- 只有 ProposedHire APPROVED + 公示 CLOSED_NO_BLOCKER + Offer ACCEPTED（学校要求时）
  + PositionReservation VALID 才允许 handoff。
- handoff 幂等：同一 proposed_hire 重复调用返回同一 HR05 case；DB 约束兜底。
- 公示绝不直接暴露 Candidate 全字段；用 public_display_name + public_fields 白名单（§13.4）。
- 结果变化必须创建新决策版本（异议 RESOLVED_CHANGE → 新 version）。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import (
    HandoffStatus,
    ObjectionStatus,
    OfferStatus,
    ProposedHireDecision,
    PublicNoticeStatus,
)


class HrProposedHire(models.Model):
    """拟录用（锁定并验证资格/选拔/体检/额度）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="proposed_hires",
        verbose_name=_("Application"),
    )
    recruitment_position_id = models.ForeignKey(
        "hr_recruitment.HrRecruitmentPosition",
        on_delete=models.PROTECT,
        related_name="proposed_hires",
        verbose_name=_("Recruitment Position"),
    )
    rank = models.PositiveIntegerField()
    final_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    reservation_id = models.UUIDField(null=True, blank=True, db_index=True)
    reservation_no = models.CharField(max_length=64, blank=True, default="")
    decision = models.CharField(
        max_length=16, choices=ProposedHireDecision.choices, default=ProposedHireDecision.PROPOSE
    )
    decision_reason = models.TextField(blank=True, default="")
    approval_status = models.CharField(
        max_length=24, choices=ProposedHireDecision.choices, default=ProposedHireDecision.PROPOSE
    )
    approved_by = models.CharField(max_length=128, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Proposed Hire")
        verbose_name_plural = _("Proposed Hires")
        constraints = [
            models.UniqueConstraint(
                fields=["recruitment_position_id", "rank"],
                name="uniq_hr_proposed_hire_rank_per_position",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "recruitment_position_id", "approval_status"]),
            models.Index(fields=["tenant_id", "application_id"]),
        ]

    def __str__(self):
        return f"{self.application_id} rank#{self.rank} [{self.approval_status}]"


class HrPublicNotice(models.Model):
    """公示（发布后 content_version 不可直接改）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    campaign_id = models.ForeignKey(
        "hr_recruitment.HrRecruitmentCampaign",
        on_delete=models.PROTECT,
        related_name="public_notices",
        verbose_name=_("Campaign"),
    )
    notice_no = models.CharField(max_length=64)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    content_version = models.PositiveIntegerField(default=1)
    published_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32, choices=PublicNoticeStatus.choices, default=PublicNoticeStatus.DRAFT
    )
    published_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Public Notice")
        verbose_name_plural = _("Public Notices")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "notice_no"],
                name="uniq_hr_public_notice_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "campaign_id", "status"]),
        ]

    def __str__(self):
        return f"{self.notice_no} [{self.status}]"


class HrPublicNoticeEntry(models.Model):
    """公示条目（只暴露白名单字段，绝不暴露 Candidate 全字段）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    notice_id = models.ForeignKey(
        HrPublicNotice,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name=_("Notice"),
    )
    proposed_hire_id = models.ForeignKey(
        HrProposedHire,
        on_delete=models.PROTECT,
        related_name="notice_entries",
        verbose_name=_("Proposed Hire"),
    )
    public_display_name = models.CharField(max_length=100)
    public_fields_json = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Public Notice Entry")
        verbose_name_plural = _("Public Notice Entries")
        constraints = [
            models.UniqueConstraint(
                fields=["notice_id", "proposed_hire_id"],
                name="uniq_hr_notice_entry",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "notice_id"]),
        ]

    def __str__(self):
        return self.public_display_name


class HrNoticeObjection(models.Model):
    """公示异议案件（结果变化必须创建新决策版本）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    notice_id = models.ForeignKey(
        HrPublicNotice,
        on_delete=models.PROTECT,
        related_name="objections",
        verbose_name=_("Notice"),
    )
    proposed_hire_id = models.ForeignKey(
        HrProposedHire,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="objections",
    )
    received_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=64, blank=True, default="")
    category = models.CharField(max_length=64, blank=True, default="")
    content = models.TextField(blank=True, default="")
    evidence = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=24, choices=ObjectionStatus.choices, default=ObjectionStatus.RECEIVED
    )
    assignee = models.CharField(max_length=128, blank=True, default="")
    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("Notice Objection")
        verbose_name_plural = _("Notice Objections")
        indexes = [
            models.Index(fields=["tenant_id", "notice_id", "status"]),
        ]

    def __str__(self):
        return f"{self.notice_id} [{self.status}]"


class HrRecruitmentOffer(models.Model):
    """Offer（DRAFT→APPROVED→ISSUED→VIEWED→ACCEPTED/DECLINED/EXPIRED/WITHDRAWN）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    proposed_hire_id = models.ForeignKey(
        HrProposedHire,
        on_delete=models.PROTECT,
        related_name="offers",
        verbose_name=_("Proposed Hire"),
    )
    offer_no = models.CharField(max_length=64)
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=OfferStatus.choices, default=OfferStatus.DRAFT
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True, default="")
    document_id = models.UUIDField(null=True, blank=True)
    employment_type = models.CharField(max_length=64, blank=True, default="")
    expected_report_date = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Recruitment Offer")
        verbose_name_plural = _("Recruitment Offers")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "offer_no"],
                name="uniq_hr_offer_no",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "proposed_hire_id", "status"]),
        ]

    def __str__(self):
        return f"{self.offer_no} [{self.status}]"


class HrRecruitmentHandoff(models.Model):
    """HANDOFF_TO_HR05 记录（幂等；同一 proposed_hire 只允许一条 handoff）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    proposed_hire_id = models.ForeignKey(
        HrProposedHire,
        on_delete=models.PROTECT,
        related_name="handoffs",
        verbose_name=_("Proposed Hire"),
    )
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="handoffs",
        verbose_name=_("Application"),
    )
    reservation_id = models.UUIDField(null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=16, choices=HandoffStatus.choices, default=HandoffStatus.CREATED
    )
    handoff_at = models.DateTimeField(auto_now_add=True)
    hr05_case_id = models.CharField(max_length=128, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True)
    payload_snapshot = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("Recruitment Handoff")
        verbose_name_plural = _("Recruitment Handoffs")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "proposed_hire_id"],
                name="uniq_hr_handoff_proposed_hire",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "proposed_hire_id"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"handoff {self.proposed_hire_id} [{self.status}]"
