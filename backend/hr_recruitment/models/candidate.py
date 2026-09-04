"""
hr_recruitment/models/candidate.py

HR04-03 候选自然人（《04_HR04_总册》§10.3）。

原则：
- 候选人 ≠ 应聘申请；一个候选自然人可有多条 HrJobApplication（§4.4）。
- candidate_uid immutable；email 只是联系字段，禁止据此自动合并 Person/候选（§23）。
- 身份证加密存储 + hash 做 tenant-scoped exact match；禁止明文日志；不跨租户 dedupe。
- consent/retention 必须记录；招聘未录用不得永远保存全部身份证/简历（§10.6）。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import CandidateStatus, IdentityMatchResult


class HrRecruitmentCandidate(models.Model):
    """招聘域中的候选自然人身份。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    candidate_uid = models.CharField(max_length=64, unique=True, editable=False)
    candidate_no = models.CharField(max_length=64, blank=True, default="")
    legal_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True, default="")
    primary_email = models.EmailField(max_length=254, blank=True, default="")
    primary_mobile = models.CharField(max_length=32, blank=True, default="")
    # 身份证：加密存储 + tenant-scoped hash（防明文日志）
    national_id_cipher = models.TextField(blank=True, default="")
    national_id_hash = models.CharField(max_length=128, blank=True, default="", db_index=True)
    consent_version = models.CharField(max_length=32, blank=True, default="")
    consent_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateField(null=True, blank=True)
    legal_hold = models.BooleanField(default=False)
    legal_hold_reason = models.CharField(max_length=300, blank=True, default="")
    anonymized_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=CandidateStatus.choices, default=CandidateStatus.ACTIVE
    )
    talent_tags = models.JSONField(default=list, blank=True)
    legacy_candidate_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Recruitment Candidate")
        verbose_name_plural = _("Recruitment Candidates")
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "candidate_no"]),
            models.Index(fields=["tenant_id", "primary_email"]),
            models.Index(fields=["tenant_id", "national_id_hash"]),
        ]

    def __str__(self):
        return f"{self.legal_name} ({self.candidate_uid})"


class HrCandidateIdentityMatch(models.Model):
    """候选去重记录（EXACT/POSSIBLE/NO_MATCH/INSUFFICIENT_DATA）。禁止自动 merge。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    source_candidate_id = models.ForeignKey(
        HrRecruitmentCandidate,
        on_delete=models.PROTECT,
        related_name="identity_matches_out",
        verbose_name=_("Source Candidate"),
    )
    target_candidate_id = models.ForeignKey(
        HrRecruitmentCandidate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_matches_in",
        verbose_name=_("Target Candidate"),
    )
    match_result = models.CharField(
        max_length=24, choices=IdentityMatchResult.choices, default=IdentityMatchResult.INSUFFICIENT_DATA
    )
    match_basis_json = models.JSONField(default=dict, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_by = models.CharField(max_length=128, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Candidate Identity Match")
        verbose_name_plural = _("Candidate Identity Matches")
        indexes = [
            models.Index(fields=["tenant_id", "match_result"]),
            models.Index(fields=["tenant_id", "resolved"]),
        ]

    def __str__(self):
        return f"{self.source_candidate_id} → {self.target_candidate_id} [{self.match_result}]"
