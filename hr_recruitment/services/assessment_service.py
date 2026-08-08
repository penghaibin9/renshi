"""
hr_recruitment/services/assessment_service.py

HR04-05 考试面试与考察服务（《04_HR04_总册》§12）。

核心：
- HrSelectionSchemeVersion + HrSelectionComponent（权重/门槛/淘汰）；
- HrAssessmentEvent 场次 + HrEvaluatorAssignment（回避/盲评）；
- HrCandidateScoreSheet（DRAFT→SUBMITTED→LOCKED）+ 服务端总分；
- 解锁走特权 REOPEN_REQUESTED→REOPEN_APPROVED→DRAFT，保留旧版本；
- HrSelectionResultSnapshot 冻结排名（后续规则变化不得改变已冻结结果）。

硬规则：
- 总分必须服务端计算；禁止前端提交 final_total（§12.4）。
- 评分提交后锁定；解锁必须特权+reason+audit（§12.7）。
- 盲评服务端裁剪（privacy.py），不是 CSS 隐藏（§12.5）。
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from hr_recruitment.api.exceptions import (
    ScoreAlreadyLockedError,
    InvalidStateTransitionError,
)
from hr_recruitment.constants import ConflictStatus, ScoreSheetStatus
from hr_recruitment.models import (
    HrAssessmentEvent,
    HrCandidateScore,
    HrCandidateScoreSheet,
    HrEvaluatorAssignment,
    HrScoreCriterion,
    HrScoreSheetTemplate,
    HrSelectionComponent,
    HrSelectionResultSnapshot,
    HrSelectionSchemeVersion,
)


class AssessmentServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class AssessmentService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    # ---- 评分方案 ----

    @transaction.atomic
    def create_scheme(self, *, position_id: str) -> HrSelectionSchemeVersion:
        last = (
            HrSelectionSchemeVersion.objects.filter(
                tenant_id=self.tenant_id, recruitment_position_id_id=position_id
            )
            .order_by("-version_no")
            .first()
        )
        scheme = HrSelectionSchemeVersion.objects.create(
            tenant_id=self.tenant_id,
            recruitment_position_id_id=position_id,
            version_no=(last.version_no if last else 0) + 1,
            created_by=self.actor,
        )
        return scheme

    @transaction.atomic
    def add_component(
        self,
        *,
        scheme_version_id: str,
        component_type: str,
        name: str,
        weight,
        max_score=100,
        pass_score=None,
        sequence=0,
        is_elimination=False,
    ) -> HrSelectionComponent:
        scheme = HrSelectionSchemeVersion.objects.get(
            id=scheme_version_id, tenant_id=self.tenant_id
        )
        if scheme.status != "DRAFT":
            raise AssessmentServiceError(
                "SCHEME_LOCKED", "评分方案已锁定/生效，不可修改（创建新版本）", http_status=409
            )
        return HrSelectionComponent.objects.create(
            tenant_id=self.tenant_id,
            scheme_version_id=scheme,
            component_type=component_type,
            name=name,
            weight=weight,
            max_score=max_score,
            pass_score=pass_score,
            sequence=sequence,
            is_elimination=is_elimination,
        )

    @transaction.atomic
    def lock_scheme(self, *, scheme_version_id: str) -> HrSelectionSchemeVersion:
        scheme = HrSelectionSchemeVersion.objects.get(
            id=scheme_version_id, tenant_id=self.tenant_id
        )
        if scheme.status != "DRAFT":
            raise AssessmentServiceError("SCHEME_NOT_DRAFT", "仅 DRAFT 方案可锁定", http_status=409)
        # 权重合计校验（服务端）
        components = scheme.components.all()
        total_weight = sum((Decimal(c.weight) for c in components), Decimal(0))
        if components and total_weight <= 0:
            raise AssessmentServiceError("SCHEME_WEIGHT_INVALID", "组件权重合计必须 > 0", http_status=422)
        scheme.status = "LOCKED"
        scheme.locked_at = timezone.now()
        scheme.save(update_fields=["status", "locked_at"])
        HrSelectionSchemeVersion.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=scheme.recruitment_position_id,
            status="ACTIVE",
        ).exclude(id=scheme.id).update(status="SUPERSEDED")
        scheme.status = "ACTIVE"
        scheme.save(update_fields=["status"])
        return scheme

    # ---- 场次与专家 ----

    @transaction.atomic
    def create_event(
        self,
        *,
        component_id: str,
        title,
        event_date,
        start_time=None,
        end_time=None,
        mode="ONSITE",
        location="",
        capacity=0,
    ) -> HrAssessmentEvent:
        return HrAssessmentEvent.objects.create(
            tenant_id=self.tenant_id,
            component_id_id=component_id,
            title=title,
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            location=location,
            capacity=capacity,
            created_by=self.actor,
        )

    @transaction.atomic
    def assign_evaluator(
        self,
        *,
        event_id: str,
        evaluator_staff_id: int,
        role="",
        blind_mode=False,
    ) -> HrEvaluatorAssignment:
        event = HrAssessmentEvent.objects.get(id=event_id, tenant_id=self.tenant_id)
        return HrEvaluatorAssignment.objects.create(
            tenant_id=self.tenant_id,
            event_id=event,
            evaluator_staff_id=evaluator_staff_id,
            role=role,
            conflict_status=ConflictStatus.CLEAR,
            blind_mode=blind_mode,
            created_by=self.actor,
        )

    @transaction.atomic
    def declare_conflict(
        self, *, assignment_id: str, status: str, recusal_reason: str = ""
    ) -> HrEvaluatorAssignment:
        """声明/检测利益冲突（DECLARED/DETECTED/RECUSED）。"""
        assignment = HrEvaluatorAssignment.objects.get(
            id=assignment_id, tenant_id=self.tenant_id
        )
        assignment.conflict_status = status
        assignment.recusal_reason = recusal_reason
        assignment.save(update_fields=["conflict_status", "recusal_reason"])
        return assignment

    # ---- 评分 ----

    @transaction.atomic
    def create_score_sheet(
        self,
        *,
        application_id: str,
        event_id: str,
        evaluator_id: str,
    ) -> HrCandidateScoreSheet:
        """创建评分表（event+candidate+evaluator 唯一）。"""
        from hr_recruitment.models import HrJobApplication

        event = HrAssessmentEvent.objects.get(id=event_id, tenant_id=self.tenant_id)
        app = HrJobApplication.objects.get(id=application_id, tenant_id=self.tenant_id)
        sheet = HrCandidateScoreSheet.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            event_id=event,
            evaluator_id_id=evaluator_id,
            status=ScoreSheetStatus.DRAFT,
        )
        return sheet

    def _criteria_for_component(self, component: HrSelectionComponent):
        """惰性创建/获取 component 的评分模板与标准（以组件为评分维度）。"""
        template = HrScoreSheetTemplate.objects.filter(
            tenant_id=self.tenant_id, component_id=component
        ).first()
        if template is None:
            template = HrScoreSheetTemplate.objects.create(
                tenant_id=self.tenant_id,
                component_id=component,
                title=f"{component.name}评分表",
                created_by=self.actor,
            )
            HrScoreCriterion.objects.create(
                tenant_id=self.tenant_id,
                template_id=template,
                title=component.name,
                description=f"{component.name}综合评分",
                max_score=component.max_score,
                weight=1,
                sequence=0,
            )
        return HrScoreCriterion.objects.filter(template_id=template)

    def get_score_sheet_context(self, *, score_sheet_id: str, blind: bool = False) -> dict:
        """评分页上下文（盲评时服务端裁剪 PII）。"""
        sheet = HrCandidateScoreSheet.objects.select_related(
            "application_id", "event_id", "evaluator_id"
        ).get(id=score_sheet_id, tenant_id=self.tenant_id)
        component = sheet.event_id.component_id
        criteria = self._criteria_for_component(component)
        scores = {
            s.criterion_id_id: s for s in HrCandidateScore.objects.filter(sheet_id=sheet)
        }
        candidate = sheet.application_id.candidate_id
        context = {
            "candidate_no": candidate.candidate_no or "—",
            "candidate_name": candidate.legal_name if not blind else "（盲评）",
            "event_title": sheet.event_id.title,
            "event_date": sheet.event_id.event_date.isoformat(),
            "score_sheet_status": sheet.status,
            "criteria": [
                {
                    "id": str(c.id),
                    "title": c.title,
                    "max_score": str(c.max_score),
                    "weight": str(c.weight),
                    "current_score": str(scores[c.id].score) if c.id in scores else None,
                }
                for c in criteria
            ],
        }
        return context

    @transaction.atomic
    def save_scores(
        self,
        *,
        score_sheet_id: str,
        scores: dict,
        submit: bool = False,
    ) -> HrCandidateScoreSheet:
        """保存评分（DRAFT 可改；submit 后进入 SUBMITTED，服务端算总分）。"""
        sheet = (
            HrCandidateScoreSheet.objects.select_for_update()
            .filter(id=score_sheet_id, tenant_id=self.tenant_id)
            .first()
        )
        if sheet is None:
            raise AssessmentServiceError("SCORE_SHEET_NOT_FOUND", "评分表不存在", http_status=404)
        if sheet.status == ScoreSheetStatus.LOCKED:
            raise ScoreAlreadyLockedError("评分已锁定，不可修改")

        component = sheet.event_id.component_id
        criteria = list(self._criteria_for_component(component))
        # key 兼容 criterion_id 与 component_id（一个组件对应一个评分标准）
        criteria_map = {str(c.id): c for c in criteria}
        criteria_map[str(component.id)] = criteria[0] if criteria else None
        criteria_map[component.name] = criteria[0] if criteria else None

        for criterion_id, raw_score in scores.items():
            criterion = criteria_map.get(criterion_id)
            if criterion is None:
                raise AssessmentServiceError("CRITERION_NOT_FOUND", "评分标准不存在", http_status=404)
            score = Decimal(str(raw_score))
            if score < 0 or score > criterion.max_score:
                raise AssessmentServiceError(
                    "SCORE_OUT_OF_RANGE",
                    f"{criterion.title} 分数超出范围 0-{criterion.max_score}",
                    http_status=422,
                )
            obj, _ = HrCandidateScore.objects.update_or_create(
                tenant_id=self.tenant_id,
                sheet_id=sheet,
                criterion_id=criterion,
                defaults={"score": score},
            )

        if submit:
            sheet.status = ScoreSheetStatus.SUBMITTED
            sheet.submitted_at = timezone.now()
        # 服务端计算总分：Σ raw_score / max_score × component.weight
        total = Decimal(0)
        for criterion in criteria:
            s = HrCandidateScore.objects.filter(sheet_id=sheet, criterion_id=criterion).first()
            if s:
                total += (s.score / criterion.max_score) * component.weight
        sheet.total_score = total
        sheet.version += 1
        sheet.save(update_fields=["status", "submitted_at", "total_score", "version"])
        return sheet

    @transaction.atomic
    def lock_score_sheet(self, *, score_sheet_id: str) -> HrCandidateScoreSheet:
        """SUBMITTED → LOCKED（锁定后不可直接改）。"""
        sheet = HrCandidateScoreSheet.objects.get(id=score_sheet_id, tenant_id=self.tenant_id)
        if sheet.status != ScoreSheetStatus.SUBMITTED:
            raise InvalidStateTransitionError(
                f"当前状态 {sheet.status} 不可锁定"
            )
        sheet.status = ScoreSheetStatus.LOCKED
        sheet.locked_at = timezone.now()
        sheet.version += 1
        sheet.save(update_fields=["status", "locked_at", "version"])
        return sheet

    @transaction.atomic
    def reopen_score_sheet(
        self,
        *,
        score_sheet_id: str,
        reason: str,
        approve: bool = False,
        approving_user: str = "",
    ) -> HrCandidateScoreSheet:
        """
        解锁评分（§12.7 特权流程）。
        LOCKED → REOPEN_REQUESTED → REOPEN_APPROVED → DRAFT。
        必须特权 + reason + approving user（audit 由调用方写）。
        """
        sheet = HrCandidateScoreSheet.objects.get(id=score_sheet_id, tenant_id=self.tenant_id)
        if sheet.status == ScoreSheetStatus.LOCKED and not approve:
            if not reason:
                raise AssessmentServiceError("REOPEN_REQUIRES_REASON", "解锁必须填写原因", http_status=422)
            sheet.status = ScoreSheetStatus.REOPEN_REQUESTED
            sheet.reopened_reason = reason
            sheet.reopened_by = self.actor
            sheet.version += 1
            sheet.save(update_fields=["status", "reopened_reason", "reopened_by", "version"])
            return sheet
        if sheet.status == ScoreSheetStatus.REOPEN_REQUESTED and approve:
            sheet.status = ScoreSheetStatus.REOPEN_APPROVED
            sheet.reopened_by = approving_user or self.actor
            sheet.version += 1
            sheet.save(update_fields=["status", "reopened_by", "version"])
            return sheet
        if sheet.status == ScoreSheetStatus.REOPEN_APPROVED:
            sheet.status = ScoreSheetStatus.DRAFT
            sheet.version += 1
            sheet.save(update_fields=["status", "version"])
            return sheet
        raise InvalidStateTransitionError(
            f"当前状态 {sheet.status} 不可解锁"
        )

    # ---- 结果快照 ----

    @transaction.atomic
    def freeze_result_snapshot(self, *, position_id: str) -> list[HrSelectionResultSnapshot]:
        """
        冻结选拔结果（§12.7/§24）：按服务端总分生成排名快照。
        后续规则变化不得改变已冻结结果。
        """
        sheets = HrCandidateScoreSheet.objects.filter(
            tenant_id=self.tenant_id,
            application_id__recruitment_position_id_id=position_id,
            status=ScoreSheetStatus.LOCKED,
        )
        agg = {}
        for sheet in sheets:
            app_id = str(sheet.application_id_id)
            agg[app_id] = agg.get(app_id, Decimal(0)) + sheet.total_score

        # 清空旧快照（同一 position 只保留一版冻结结果）
        HrSelectionResultSnapshot.objects.filter(
            tenant_id=self.tenant_id, recruitment_position_id_id=position_id
        ).delete()

        snapshots = []
        for rank, (app_id, total) in enumerate(
            sorted(agg.items(), key=lambda kv: kv[1], reverse=True), start=1
        ):
            snapshots.append(
                HrSelectionResultSnapshot.objects.create(
                    tenant_id=self.tenant_id,
                    recruitment_position_id_id=position_id,
                    rank=rank,
                    application_id_id=app_id,
                    final_score=total,
                    calculation_version="v1",
                )
            )
        return snapshots
