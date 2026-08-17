"""
hr_qualification/models/review.py —— 评审全链（总册 §70-80）。

ReviewPanel + PanelMember + ScoreSheet + PanelDecision + FinalDecision
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_qualification.constants import (
    ConflictStatus,
    FinalDecisionType,
    PanelDecisionType,
    PanelMemberRole,
    ReviewMethod,
    ScoreSheetStatus,
    VoteChoice,
)


class HrDoubleTeacherReviewPanel(models.Model):
    """双师评审组。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherRecognitionBatch",
        on_delete=models.PROTECT,
        related_name="review_panels",
    )
    panel_no = models.CharField(max_length=32)
    discipline_scope = models.CharField(max_length=200, blank=True, default="")
    member_ids = models.JSONField(null=True, blank=True)  # 成员列表
    recusal_policy = models.CharField(max_length=200, blank=True, default="")
    scoring_scheme_version = models.CharField(max_length=64, blank=True, default="")
    review_method = models.CharField(
        max_length=24,
        choices=ReviewMethod.choices,
        default=ReviewMethod.RULE_CONFIRMATION,
    )
    status = models.CharField(max_length=24, blank=True, default="DRAFT")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Review Panel")
        verbose_name_plural = _("HR Double Teacher Review Panels")
        indexes = [
            models.Index(fields=["batch_id"]),
        ]

    def __str__(self) -> str:
        return f"Panel {self.panel_no} [{self.discipline_scope}]"


class HrDoubleTeacherPanelMember(models.Model):
    """评审组成员。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    panel_id = models.ForeignKey(
        HrDoubleTeacherReviewPanel,
        on_delete=models.CASCADE,
        related_name="panel_members",
    )
    reviewer_ref = models.CharField(max_length=200)  # reviewer ID / 外部 ID
    role = models.CharField(
        max_length=16, choices=PanelMemberRole.choices, default=PanelMemberRole.MEMBER
    )
    expertise = models.CharField(max_length=200, blank=True, default="")
    conflict_status = models.CharField(
        max_length=16,
        choices=ConflictStatus.choices,
        default=ConflictStatus.CLEAR,
    )
    access_scope = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("HR Double Teacher Panel Member")
        verbose_name_plural = _("HR Double Teacher Panel Members")
        indexes = [
            models.Index(fields=["panel_id"]),
        ]

    def __str__(self) -> str:
        return f"Member {self.reviewer_ref} [{self.role}]"


class HrDoubleTeacherScoreSheet(models.Model):
    """评分表（DRAFT→SUBMITTED→LOCKED）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        related_name="score_sheets",
    )
    panel_member_id = models.ForeignKey(
        HrDoubleTeacherPanelMember,
        on_delete=models.PROTECT,
        related_name="score_sheets",
    )
    rubric_version_id = models.CharField(max_length=64, blank=True, default="")
    scores_json = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ScoreSheetStatus.choices,
        default=ScoreSheetStatus.DRAFT,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Score Sheet")
        verbose_name_plural = _("HR Double Teacher Score Sheets")
        indexes = [
            models.Index(fields=["application_id", "panel_member_id"]),
        ]

    def __str__(self) -> str:
        return f"ScoreSheet App#{self.application_id_id} [{self.status}]"


class HrDoubleTeacherVote(models.Model):
    """投票记录。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    panel_id = models.ForeignKey(
        HrDoubleTeacherReviewPanel,
        on_delete=models.PROTECT,
        related_name="votes",
    )
    application_id = models.ForeignKey(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        related_name="votes",
    )
    panel_member_id = models.ForeignKey(
        HrDoubleTeacherPanelMember,
        on_delete=models.PROTECT,
        related_name="votes",
    )
    choice = models.CharField(max_length=16, choices=VoteChoice.choices)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Double Teacher Vote")
        verbose_name_plural = _("HR Double Teacher Votes")
        constraints = [
            models.UniqueConstraint(
                fields=["application_id", "panel_member_id"],
                name="uniq_vote_app_member",
            ),
        ]

    def __str__(self) -> str:
        return f"Vote App#{self.application_id_id} → {self.choice}"


class HrDoubleTeacherPanelDecision(models.Model):
    """评审组决策。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_id = models.OneToOneField(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        related_name="panel_decision",
    )
    panel_id = models.ForeignKey(
        HrDoubleTeacherReviewPanel,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    recommended_level = models.CharField(max_length=32, blank=True, default="")
    decision = models.CharField(
        max_length=32,
        choices=PanelDecisionType.choices,
        default=PanelDecisionType.RECOMMEND_RECOGNIZE,
    )
    reason_summary = models.TextField(blank=True, default="")
    score_summary = models.JSONField(null=True, blank=True)
    vote_summary = models.JSONField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Panel Decision")
        verbose_name_plural = _("HR Double Teacher Panel Decisions")

    def __str__(self) -> str:
        return f"PanelDecision App#{self.application_id_id} → {self.decision}"


class HrDoubleTeacherFinalDecision(models.Model):
    """学校最终认定。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application_id = models.OneToOneField(
        "hr_qualification.HrDoubleTeacherApplication",
        on_delete=models.PROTECT,
        related_name="final_decision",
    )
    decision = models.CharField(
        max_length=32,
        choices=FinalDecisionType.choices,
        default=FinalDecisionType.RECOGNIZE,
    )
    recognized_level = models.CharField(max_length=32, null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    decision_authority = models.CharField(max_length=200, blank=True, default="")
    meeting_ref = models.CharField(max_length=200, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Double Teacher Final Decision")
        verbose_name_plural = _("HR Double Teacher Final Decisions")

    def __str__(self) -> str:
        return f"FinalDecision App#{self.application_id_id} → {self.decision}"
