"""
hr_qualification/models/review.py —— 评审全链（总册 §70-80）。

ReviewPanel + PanelMember + ScoreSheet + PanelDecision + FinalDecision
"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone
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


class FinalDecisionQuerySet(models.QuerySet):
    """Formal school decisions have no bulk mutation escape hatch."""

    _ERROR = (
        "HR09_FINAL_DECISION_APPEND_ONLY: use FinalDecisionAuthorityService "
        "to append a correction or revocation"
    )

    def update(self, **kwargs):
        raise ValueError(self._ERROR)

    def delete(self):
        raise ValueError(self._ERROR)

    def bulk_create(self, objs, **kwargs):
        raise ValueError(self._ERROR)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError(self._ERROR)


class FinalDecisionAmendmentQuerySet(models.QuerySet):
    """Correction/revocation rows are an append-only authority ledger."""

    _ERROR = "HR09_FINAL_DECISION_AMENDMENT_APPEND_ONLY"

    def update(self, **kwargs):
        raise ValueError(self._ERROR)

    def delete(self):
        raise ValueError(self._ERROR)

    def bulk_create(self, objs, **kwargs):
        raise ValueError(self._ERROR)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValueError(self._ERROR)


class HrDoubleTeacherFinalDecision(models.Model):
    """学校最终认定；发布后只允许追加更正/撤销事实。"""

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
    authority_receipt_json = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    sealed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    published_by = models.PositiveBigIntegerField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = FinalDecisionQuerySet.as_manager()

    _HASH_FIELDS = (
        "id",
        "application_id_id",
        "decision",
        "recognized_level",
        "effective_from",
        "effective_to",
        "decision_authority",
        "meeting_ref",
        "published_at",
        "version",
        "authority_receipt_json",
        "sealed_at",
        "published_by",
    )

    class Meta:
        verbose_name = _("HR Double Teacher Final Decision")
        verbose_name_plural = _("HR Double Teacher Final Decisions")
        permissions = [
            ("hr.qualification.review.final_decision.correct", "Append HR09 final-decision correction"),
            ("hr.qualification.review.final_decision.revoke", "Append HR09 final-decision revocation"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(published_at__isnull=True, sealed_at__isnull=True, content_hash="")
                    | (
                        Q(published_at__isnull=False)
                        & Q(sealed_at__isnull=False)
                        & ~Q(content_hash="")
                        & Q(published_by__isnull=False)
                    )
                ),
                name="ck_hr09_final_decision_seal",
            ),
        ]

    def __str__(self) -> str:
        return f"FinalDecision App#{self.application_id_id} → {self.decision}"

    @staticmethod
    def _canonical(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def calculate_content_hash(self) -> str:
        payload = {
            field: self._canonical(getattr(self, field))
            for field in self._HASH_FIELDS
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    def verify_content_hash(self) -> bool:
        return bool(self.sealed_at and self.content_hash) and (
            self.content_hash == self.calculate_content_hash()
        )

    def seal(self, *, actor_user_id: int | None, authority_receipt: dict):
        if self.sealed_at is not None:
            if self.verify_content_hash():
                return self
            raise ValueError("HR09_FINAL_DECISION_HASH_MISMATCH")
        if not self.published_at:
            self.published_at = timezone.now()
        if not isinstance(authority_receipt, dict) or not authority_receipt.get(
            "permissionCode"
        ):
            raise ValueError("HR09_FINAL_DECISION_AUTHORITY_RECEIPT_REQUIRED")
        self.published_by = int(actor_user_id or 0)
        self.authority_receipt_json = dict(authority_receipt)
        self.sealed_at = timezone.now()
        self.content_hash = self.calculate_content_hash()
        self._allow_seal = True
        try:
            self.save(force_insert=self._state.adding)
        finally:
            self._allow_seal = False
        return self

    def save(self, *args, **kwargs):
        persisted = None
        if not self._state.adding:
            persisted = (
                type(self).objects.filter(pk=self.pk)
                .values("sealed_at")
                .first()
            )
        if persisted and persisted["sealed_at"] is not None:
            raise ValueError(
                "HR09_FINAL_DECISION_APPEND_ONLY: sealed decisions cannot be updated"
            )
        if self.published_at is not None:
            if self.sealed_at is None or not getattr(self, "_allow_seal", False):
                raise ValueError(
                    "HR09_FINAL_DECISION_SERVICE_REQUIRED: publication must be sealed"
                )
            if self.content_hash != self.calculate_content_hash():
                raise ValueError("HR09_FINAL_DECISION_HASH_MISMATCH")
        elif self.sealed_at is not None or self.content_hash:
            raise ValueError("HR09_FINAL_DECISION_DRAFT_CANNOT_BE_SEALED")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.sealed_at is not None:
            raise ValueError(
                "HR09_FINAL_DECISION_APPEND_ONLY: sealed decisions cannot be deleted"
            )
        return super().delete(*args, **kwargs)


class HrDoubleTeacherFinalDecisionAmendment(models.Model):
    """Immutable correction/revocation appended to a sealed final decision."""

    class Kind(models.TextChoices):
        CORRECTION = "CORRECTION", "Correction"
        REVOCATION = "REVOCATION", "Revocation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    source_decision_id = models.ForeignKey(
        HrDoubleTeacherFinalDecision,
        on_delete=models.PROTECT,
        related_name="authority_amendments",
    )
    supersedes_amendment_id = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor_amendment",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    replacement_payload_json = models.JSONField(default=dict, blank=True)
    effect_receipt_json = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    authority_ref = models.CharField(max_length=200)
    authority_receipt_json = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=128)
    content_hash = models.CharField(max_length=64)
    sealed_at = models.DateTimeField(db_index=True)
    published_by = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FinalDecisionAmendmentQuerySet.as_manager()

    _HASH_FIELDS = (
        "id",
        "tenant_id",
        "source_decision_id_id",
        "supersedes_amendment_id_id",
        "kind",
        "replacement_payload_json",
        "effect_receipt_json",
        "reason",
        "authority_ref",
        "authority_receipt_json",
        "idempotency_key",
        "sealed_at",
        "published_by",
    )

    class Meta:
        verbose_name = _("HR Double Teacher Final Decision Amendment")
        verbose_name_plural = _("HR Double Teacher Final Decision Amendments")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr09_decision_amendment_key",
            ),
            models.CheckConstraint(
                condition=~Q(content_hash=""),
                name="ck_hr09_decision_amendment_hash",
            ),
        ]
        indexes = [
            models.Index(
                fields=("tenant_id", "source_decision_id", "created_at"),
                name="idx_hr09_decision_amendment",
            ),
        ]

    @staticmethod
    def _canonical(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def calculate_content_hash(self) -> str:
        payload = {
            field: self._canonical(getattr(self, field))
            for field in self._HASH_FIELDS
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    def verify_content_hash(self) -> bool:
        return bool(self.sealed_at and self.content_hash) and (
            self.content_hash == self.calculate_content_hash()
        )

    def seal(self):
        if not self.sealed_at:
            self.sealed_at = timezone.now()
        self.content_hash = self.calculate_content_hash()
        self._allow_create = True
        try:
            self.save(force_insert=True)
        finally:
            self._allow_create = False
        return self

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HR09_FINAL_DECISION_AMENDMENT_APPEND_ONLY")
        if not getattr(self, "_allow_create", False):
            raise ValueError("HR09_FINAL_DECISION_AMENDMENT_SERVICE_REQUIRED")
        if not self.verify_content_hash():
            raise ValueError("HR09_FINAL_DECISION_AMENDMENT_HASH_MISMATCH")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR09_FINAL_DECISION_AMENDMENT_APPEND_ONLY")
