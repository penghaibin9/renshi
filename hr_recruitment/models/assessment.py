"""
hr_recruitment/models/assessment.py

HR04-05 考试面试与考察（《04_HR04_总册》§12）。

HrSelectionComponent（挂 SchemeVersion）
HrAssessmentEvent（场次）+ HrEvaluatorAssignment（专家分配/回避/盲评）
HrScoreSheetTemplate / HrScoreCriterion / HrCandidateScoreSheet / HrCandidateScore
HrSelectionResultSnapshot（结果冻结，排名不可被后续规则变化改变）
HrMedicalCheck / HrBackgroundCheck（体检/考察，HIGH_SENSITIVE 隔离）

硬规则：
- 总分必须服务端计算；禁止前端提交 final_total（§12.4/§24）。
- 评分提交 DRAFT→SUBMITTED→LOCKED；解锁走特权 REOPEN_REQUESTED→REOPEN_APPROVED→DRAFT，
  必须保留旧版本（§12.7）。
- 盲评服务端裁剪（§12.5），不是 CSS 隐藏。
- 医疗信息 HIGH_SENSITIVE，普通管理员默认只看结论（§12.8）。
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_recruitment.constants import (
    AssessmentEventStatus,
    AssessmentMode,
    BackgroundCheckStatus,
    ConflictStatus,
    MedicalCheckStatus,
    ScoreSheetStatus,
    SelectionComponentType,
    SensitiveLevel,
)


class HrSelectionComponent(models.Model):
    """选拔组件（笔试/试讲/面试/技能等，挂 SelectionSchemeVersion）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    scheme_version_id = models.ForeignKey(
        "hr_recruitment.HrSelectionSchemeVersion",
        on_delete=models.CASCADE,
        related_name="components",
        verbose_name=_("Scheme Version"),
    )
    component_type = models.CharField(
        max_length=32, choices=SelectionComponentType.choices
    )
    name = models.CharField(max_length=100)
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=100)
    pass_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    sequence = models.IntegerField(default=0)
    is_elimination = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Selection Component")
        verbose_name_plural = _("Selection Components")
        constraints = [
            models.UniqueConstraint(
                fields=["scheme_version_id", "name"],
                name="uniq_hr_sel_component_scheme_name",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "scheme_version_id", "sequence"]),
        ]

    def __str__(self):
        return f"{self.name} (×{self.weight})"


class HrAssessmentEvent(models.Model):
    """考核场次。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    component_id = models.ForeignKey(
        HrSelectionComponent,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("Component"),
    )
    title = models.CharField(max_length=200)
    event_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    mode = models.CharField(
        max_length=16, choices=AssessmentMode.choices, default=AssessmentMode.ONSITE
    )
    location = models.CharField(max_length=200, blank=True, default="")
    online_url = models.CharField(max_length=500, blank=True, default="")
    capacity = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=24,
        choices=AssessmentEventStatus.choices,
        default=AssessmentEventStatus.DRAFT,
    )
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    version = models.PositiveIntegerField(default=1)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Assessment Event")
        verbose_name_plural = _("Assessment Events")
        indexes = [
            models.Index(fields=["tenant_id", "component_id", "event_date"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.title} {self.event_date}"


class HrEvaluatorAssignment(models.Model):
    """专家/评估人分配 + 回避 + 盲评。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_id = models.ForeignKey(
        HrAssessmentEvent,
        on_delete=models.PROTECT,
        related_name="evaluators",
        verbose_name=_("Event"),
    )
    evaluator_staff_id = models.BigIntegerField(db_index=True)
    evaluator_name = models.CharField(max_length=128, blank=True, default="")
    role = models.CharField(max_length=32, blank=True, default="")
    conflict_status = models.CharField(
        max_length=16, choices=ConflictStatus.choices, default=ConflictStatus.CLEAR
    )
    recusal_reason = models.TextField(blank=True, default="")
    blind_mode = models.BooleanField(default=False)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Evaluator Assignment")
        verbose_name_plural = _("Evaluator Assignments")
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "evaluator_staff_id"],
                name="uniq_hr_evaluator_event_staff",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "event_id", "conflict_status"]),
        ]

    def __str__(self):
        return f"{self.evaluator_name} [{self.conflict_status}]"


class HrScoreSheetTemplate(models.Model):
    """评分表模板。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    component_id = models.ForeignKey(
        HrSelectionComponent,
        on_delete=models.PROTECT,
        related_name="score_templates",
        verbose_name=_("Component"),
    )
    title = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Score Sheet Template")
        verbose_name_plural = _("Score Sheet Templates")

    def __str__(self):
        return self.title


class HrScoreCriterion(models.Model):
    """评分标准项。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    template_id = models.ForeignKey(
        HrScoreSheetTemplate,
        on_delete=models.CASCADE,
        related_name="criteria",
        verbose_name=_("Template"),
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=100)
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    sequence = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("Score Criterion")
        verbose_name_plural = _("Score Criteria")
        indexes = [
            models.Index(fields=["tenant_id", "template_id", "sequence"]),
        ]

    def __str__(self):
        return self.title


class HrCandidateScoreSheet(models.Model):
    """候选人评分表（event+candidate+evaluator 唯一；锁定后不可改）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="score_sheets",
        verbose_name=_("Application"),
    )
    event_id = models.ForeignKey(
        HrAssessmentEvent,
        on_delete=models.PROTECT,
        related_name="score_sheets",
        verbose_name=_("Event"),
    )
    evaluator_id = models.ForeignKey(
        HrEvaluatorAssignment,
        on_delete=models.PROTECT,
        related_name="score_sheets",
        verbose_name=_("Evaluator"),
    )
    status = models.CharField(
        max_length=24, choices=ScoreSheetStatus.choices, default=ScoreSheetStatus.DRAFT
    )
    total_score = models.DecimalField(
        max_digits=8, decimal_places=2, default=0
    )  # 服务端计算
    submitted_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    reopened_reason = models.TextField(blank=True, default="")
    reopened_by = models.CharField(max_length=128, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Candidate Score Sheet")
        verbose_name_plural = _("Candidate Score Sheets")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "event_id", "application_id", "evaluator_id"],
                name="uniq_hr_score_sheet_event_app_eval",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "event_id", "application_id"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"{self.application_id} {self.event_id} [{self.status}]"


class HrCandidateScore(models.Model):
    """评分项得分（总分服务端计算，不存前端提交的 total）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    sheet_id = models.ForeignKey(
        HrCandidateScoreSheet,
        on_delete=models.CASCADE,
        related_name="scores",
        verbose_name=_("Score Sheet"),
    )
    criterion_id = models.ForeignKey(
        HrScoreCriterion,
        on_delete=models.PROTECT,
        related_name="candidate_scores",
        verbose_name=_("Criterion"),
    )
    score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    comment = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("Candidate Score")
        verbose_name_plural = _("Candidate Scores")
        constraints = [
            models.UniqueConstraint(
                fields=["sheet_id", "criterion_id"],
                name="uniq_hr_candidate_score_sheet_criterion",
            ),
        ]

    def __str__(self):
        return f"{self.sheet_id} {self.criterion_id} = {self.score}"


class HrSelectionResultSnapshot(models.Model):
    """选拔结果快照（冻结排名；后续规则变化不得改变已冻结结果）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    recruitment_position_id = models.ForeignKey(
        "hr_recruitment.HrRecruitmentPosition",
        on_delete=models.PROTECT,
        related_name="result_snapshots",
        verbose_name=_("Recruitment Position"),
    )
    scheme_version_id = models.UUIDField(null=True, blank=True, db_index=True)
    snapshot_version = models.PositiveIntegerField(default=1)
    rank = models.PositiveIntegerField()
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="result_snapshots",
        verbose_name=_("Application"),
    )
    final_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    calculation_version = models.CharField(max_length=32, blank=True, default="")
    calculated_at = models.DateTimeField(auto_now_add=True)
    snapshot_json = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Selection Result Snapshot")
        verbose_name_plural = _("Selection Result Snapshots")
        constraints = [
            models.UniqueConstraint(
                fields=["recruitment_position_id", "snapshot_version", "rank"],
                name="uniq_hr_selection_rank_per_version",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "recruitment_position_id", "snapshot_version", "rank"]),
        ]

    def __str__(self):
        return f"{self.recruitment_position_id} rank#{self.rank}"


class HrAssessmentParticipant(models.Model):
    """候选参加场次记录（§39 排期冲突：同候选多场冲突/容量校验）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    event_id = models.ForeignKey(
        HrAssessmentEvent,
        on_delete=models.PROTECT,
        related_name="participants",
        verbose_name=_("Event"),
    )
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="assessment_participations",
        verbose_name=_("Application"),
    )
    created_by = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Assessment Participant")
        verbose_name_plural = _("Assessment Participants")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "event_id", "application_id"],
                name="uniq_hr_assessment_participant_event_app",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "event_id"]),
            models.Index(fields=["tenant_id", "application_id"]),
        ]

    def __str__(self):
        return f"{self.application_id} → {self.event_id}"


class HrMedicalCheck(models.Model):
    """体检（HIGH_SENSITIVE：普通管理员默认只看结论）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="medical_checks",
        verbose_name=_("Application"),
    )
    status = models.CharField(
        max_length=16, choices=MedicalCheckStatus.choices, default=MedicalCheckStatus.PENDING
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    result = models.CharField(
        max_length=16, choices=MedicalCheckStatus.choices, default=MedicalCheckStatus.PENDING
    )
    sensitive_material_id = models.UUIDField(null=True, blank=True)
    verified_by = models.CharField(max_length=128, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Medical Check")
        verbose_name_plural = _("Medical Checks")
        indexes = [
            models.Index(fields=["tenant_id", "application_id"]),
        ]

    def __str__(self):
        return f"{self.application_id} [{self.result}]"


class HrBackgroundCheck(models.Model):
    """考察/政审。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    application_id = models.ForeignKey(
        "hr_recruitment.HrJobApplication",
        on_delete=models.PROTECT,
        related_name="background_checks",
        verbose_name=_("Application"),
    )
    status = models.CharField(
        max_length=16, choices=BackgroundCheckStatus.choices, default=BackgroundCheckStatus.PENDING
    )
    result = models.CharField(
        max_length=16, choices=BackgroundCheckStatus.choices, default=BackgroundCheckStatus.PENDING
    )
    summary = models.TextField(blank=True, default="")
    sensitive_material_id = models.UUIDField(null=True, blank=True)
    verified_by = models.CharField(max_length=128, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Background Check")
        verbose_name_plural = _("Background Checks")
        indexes = [
            models.Index(fields=["tenant_id", "application_id"]),
        ]

    def __str__(self):
        return f"{self.application_id} [{self.result}]"
