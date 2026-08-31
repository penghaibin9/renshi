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

import hashlib
import json
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
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
    HrRecruitmentPosition,
    HrScoreCriterion,
    HrScoreSheetRevision,
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
    def __init__(
        self,
        *,
        tenant_id: int,
        actor: str = "",
        actor_user_id: int | None = None,
        allow_score_override: bool = False,
        enforce_score_actor: bool = False,
    ):
        self.tenant_id = tenant_id
        self.actor = actor
        self.actor_user_id = actor_user_id
        self.allow_score_override = allow_score_override
        self.enforce_score_actor = enforce_score_actor

    @staticmethod
    def _decimal_evidence(value) -> str:
        """Canonicalize DecimalField evidence before and after a DB round trip."""
        return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")

    def _assert_score_actor(self, sheet: HrCandidateScoreSheet) -> None:
        """Only the assigned auth principal may read/write a score sheet."""
        if not self.enforce_score_actor:
            return
        assigned_user_id = sheet.evaluator_id.evaluator_auth_user_id
        if assigned_user_id is not None and assigned_user_id == self.actor_user_id:
            return
        if self.allow_score_override:
            from hr_recruitment.services.audit_service import audit_event

            audit_event(
                tenant_id=self.tenant_id,
                event_type="hr.recruitment.score_sheet.override_accessed",
                business_object="HrCandidateScoreSheet",
                business_object_id=sheet.id,
                actor_id=self.actor,
                action="OVERRIDE_ACCESS",
                summary="特权账号代评/查看评分表",
            )
            return
        raise AssessmentServiceError(
            "SCORE_EVALUATOR_MISMATCH",
            "当前账号不是该评分表分配的评委",
            http_status=403,
        )

    def _write_score_event(self, sheet, event_type: str, action: str, summary: str) -> None:
        from hr_recruitment.services.audit_service import audit_event

        audit_event(
            tenant_id=self.tenant_id,
            event_type=event_type,
            business_object="HrCandidateScoreSheet",
            business_object_id=sheet.id,
            actor_id=self.actor,
            action=action,
            summary=summary,
            after={"status": sheet.status, "version": sheet.version},
        )

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
        scheme = HrSelectionSchemeVersion.objects.select_related(
            "recruitment_position_id"
        ).get(id=scheme_version_id, tenant_id=self.tenant_id)
        if scheme.status != "DRAFT":
            raise AssessmentServiceError("SCHEME_NOT_DRAFT", "仅 DRAFT 方案可锁定", http_status=409)
        # 行锁岗位：同岗位方案锁定串行化，防并发产生多个 ACTIVE 方案
        HrRecruitmentPosition.objects.select_for_update().get(
            id=scheme.recruitment_position_id_id, tenant_id=self.tenant_id
        )
        # 权重校验（服务端）：每个组件 weight > 0
        components = list(scheme.components.all())
        if not components:
            raise AssessmentServiceError("SCHEME_NO_COMPONENTS", "评分方案至少需要一个组件", http_status=422)
        for comp in components:
            if comp.weight <= 0:
                raise AssessmentServiceError(
                    "SCHEME_WEIGHT_INVALID", f"组件 {comp.name} 权重必须 > 0", http_status=422
                )
        HrSelectionSchemeVersion.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=scheme.recruitment_position_id,
            status="ACTIVE",
        ).exclude(id=scheme.id).update(status="SUPERSEDED")
        scheme.status = "ACTIVE"
        scheme.locked_at = timezone.now()
        scheme.save(update_fields=["status", "locked_at"])
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
        evaluator_auth_user_id: int | None = None,
        role="",
        blind_mode=False,
    ) -> HrEvaluatorAssignment:
        event = HrAssessmentEvent.objects.get(id=event_id, tenant_id=self.tenant_id)
        if self.enforce_score_actor and not evaluator_auth_user_id:
            raise AssessmentServiceError(
                "EVALUATOR_ACCOUNT_REQUIRED",
                "必须绑定评委登录账号，禁止创建无法归属责任人的评分分配",
                http_status=422,
            )
        return HrEvaluatorAssignment.objects.create(
            tenant_id=self.tenant_id,
            event_id=event,
            evaluator_staff_id=evaluator_staff_id,
            evaluator_auth_user_id=evaluator_auth_user_id,
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

    # ---- 排期与冲突（§39）----

    @transaction.atomic
    def assign_participant(self, *, event_id: str, application_id: str) -> HrAssessmentParticipant:
        """候选参加场次（含排期冲突/容量检查）。"""
        from hr_recruitment.models import HrAssessmentParticipant, HrJobApplication

        event = HrAssessmentEvent.objects.get(id=event_id, tenant_id=self.tenant_id)
        app = HrJobApplication.objects.get(id=application_id, tenant_id=self.tenant_id)
        conflicts = self.check_schedule_conflicts(event_id=event_id, application_id=application_id)
        if conflicts:
            raise AssessmentServiceError(
                "SCHEDULE_CONFLICT",
                "；".join(conflicts),
                http_status=409,
            )
        if event.capacity > 0:
            booked = HrAssessmentParticipant.objects.filter(
                tenant_id=self.tenant_id, event_id=event
            ).count()
            if booked >= event.capacity:
                raise AssessmentServiceError(
                    "EVENT_CAPACITY_FULL", f"场次已满（容量 {event.capacity}）", http_status=409
                )
        return HrAssessmentParticipant.objects.create(
            tenant_id=self.tenant_id,
            event_id=event,
            application_id=app,
            created_by=self.actor,
        )

    def check_schedule_conflicts(self, *, event_id: str, application_id: str) -> list[str]:
        """排期冲突检查（§39）：候选跨场时间冲突（V1）。返回冲突描述列表（空=无冲突）。"""
        from hr_recruitment.models import HrAssessmentParticipant

        event = HrAssessmentEvent.objects.filter(id=event_id, tenant_id=self.tenant_id).first()
        if event is None:
            raise AssessmentServiceError("EVENT_NOT_FOUND", "场次不存在", http_status=404)
        conflicts: list[str] = []
        same_day_participations = HrAssessmentParticipant.objects.filter(
            tenant_id=self.tenant_id,
            application_id_id=application_id,
            event_id__event_date=event.event_date,
        ).exclude(event_id_id=event_id)
        if same_day_participations.exists():
            other_events = same_day_participations.values_list("event_id__title", flat=True)
            conflicts.append(f"候选人当天已安排其他场次: {', '.join(other_events)}")
        return conflicts

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

        event = HrAssessmentEvent.objects.select_related(
            "component_id__scheme_version_id"
        ).get(id=event_id, tenant_id=self.tenant_id)
        app = HrJobApplication.objects.get(id=application_id, tenant_id=self.tenant_id)
        evaluator = HrEvaluatorAssignment.objects.filter(
            id=evaluator_id,
            tenant_id=self.tenant_id,
            event_id=event,
        ).first()
        if evaluator is None:
            raise AssessmentServiceError(
                "EVALUATOR_ASSIGNMENT_MISMATCH",
                "评委分配不属于当前学校或当前场次",
                http_status=403,
            )
        if evaluator.conflict_status not in (ConflictStatus.CLEAR, ConflictStatus.OVERRIDDEN):
            raise AssessmentServiceError(
                "EVALUATOR_RECUSED",
                "该评委存在未解除的回避冲突，禁止创建评分表",
                http_status=409,
            )
        scheme_position_id = event.component_id.scheme_version_id.recruitment_position_id_id
        if app.recruitment_position_id_id != scheme_position_id:
            raise AssessmentServiceError(
                "ASSESSMENT_POSITION_MISMATCH",
                "申请岗位与评分场次的选拔方案不一致",
                http_status=409,
            )
        sheet = HrCandidateScoreSheet.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            event_id=event,
            evaluator_id=evaluator,
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
        self._assert_score_actor(sheet)
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
            "version": sheet.version,
            "evidence_checksum": (
                sheet.revisions.order_by("-revision_no")
                .values_list("checksum", flat=True)
                .first()
            ),
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
        expected_version: int | None = None,
    ) -> HrCandidateScoreSheet:
        """保存评分（DRAFT 可改；submit 后进入 SUBMITTED，服务端算总分）。"""
        sheet = (
            HrCandidateScoreSheet.objects.select_for_update()
            .filter(id=score_sheet_id, tenant_id=self.tenant_id)
            .first()
        )
        if sheet is None:
            raise AssessmentServiceError("SCORE_SHEET_NOT_FOUND", "评分表不存在", http_status=404)
        self._assert_score_actor(sheet)
        if expected_version is not None and sheet.version != expected_version:
            raise AssessmentServiceError(
                "VERSION_CONFLICT", "评分表版本已变化，请刷新后重试", http_status=409
            )
        if sheet.status != ScoreSheetStatus.DRAFT:
            # SUBMITTED and later states are immutable until the privileged
            # reopen workflow has returned the sheet to DRAFT.
            raise ScoreAlreadyLockedError(
                f"评分表状态 {sheet.status} 不可编辑（需特权解锁回到 DRAFT）"
            )

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
            try:
                score = Decimal(str(raw_score))
            except Exception:  # noqa: BLE001
                raise AssessmentServiceError(
                    "SCORE_INVALID", f"{criterion.title} 分数必须是数字", http_status=422
                )
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
            # 提交前校验：所有 criterion 必须已打分（禁止部分分提交）
            missing = [c for c in criteria if not HrCandidateScore.objects.filter(
                sheet_id=sheet, criterion_id=c
            ).exists()]
            if missing:
                raise AssessmentServiceError(
                    "SCORE_INCOMPLETE",
                    f"以下评分项未打分: {', '.join(c.title for c in missing)}",
                    http_status=422,
                )
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
        if submit:
            self._create_score_revision(sheet)
            self._write_score_event(
                sheet,
                "hr.recruitment.score_sheet.submitted",
                "SUBMIT",
                "评分提交并生成不可变版本证据",
            )
        return sheet

    def _create_score_revision(self, sheet: HrCandidateScoreSheet) -> HrScoreSheetRevision:
        previous = sheet.revisions.order_by("-revision_no").first()
        revision_no = (previous.revision_no if previous else 0) + 1
        score_rows = [
            {
                "criterionId": str(row.criterion_id_id),
                "score": self._decimal_evidence(row.score),
                "comment": row.comment,
            }
            for row in sheet.scores.order_by("criterion_id_id")
        ]
        evidence = {
            "tenantId": self.tenant_id,
            "sheetId": str(sheet.id),
            "revisionNo": revision_no,
            "scores": score_rows,
            "totalScore": self._decimal_evidence(sheet.total_score),
            "previousChecksum": previous.checksum if previous else "",
        }
        checksum = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        return HrScoreSheetRevision.objects.create(
            tenant_id=self.tenant_id,
            sheet_id=sheet,
            revision_no=revision_no,
            scores_json=score_rows,
            total_score=sheet.total_score,
            previous_checksum=previous.checksum if previous else "",
            checksum=checksum,
            submitted_by_user_id=self.actor_user_id,
        )

    def _verify_score_revision(self, sheet: HrCandidateScoreSheet) -> HrScoreSheetRevision:
        revision = sheet.revisions.order_by("-revision_no").first()
        if revision is None:
            raise AssessmentServiceError(
                "SCORE_EVIDENCE_MISSING",
                "评分缺少不可变提交证据，禁止封板或参与排名",
                http_status=409,
            )
        current_scores = [
            {
                "criterionId": str(row.criterion_id_id),
                "score": self._decimal_evidence(row.score),
                "comment": row.comment,
            }
            for row in sheet.scores.order_by("criterion_id_id")
        ]
        evidence = {
            "tenantId": self.tenant_id,
            "sheetId": str(sheet.id),
            "revisionNo": revision.revision_no,
            "scores": revision.scores_json,
            "totalScore": self._decimal_evidence(revision.total_score),
            "previousChecksum": revision.previous_checksum,
        }
        expected_checksum = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        if (
            revision.tenant_id != self.tenant_id
            or revision.scores_json != current_scores
            or revision.total_score != sheet.total_score
            or revision.checksum != expected_checksum
        ):
            raise AssessmentServiceError(
                "SCORE_EVIDENCE_TAMPERED",
                "评分内容与提交证据不一致，禁止封板或参与排名",
                http_status=409,
            )
        return revision

    @transaction.atomic
    def lock_score_sheet(self, *, score_sheet_id: str) -> HrCandidateScoreSheet:
        """SUBMITTED → LOCKED（锁定后不可直接改）。"""
        sheet = HrCandidateScoreSheet.objects.get(id=score_sheet_id, tenant_id=self.tenant_id)
        if sheet.status != ScoreSheetStatus.SUBMITTED:
            raise InvalidStateTransitionError(
                f"当前状态 {sheet.status} 不可锁定"
            )
        self._verify_score_revision(sheet)
        sheet.status = ScoreSheetStatus.LOCKED
        sheet.locked_at = timezone.now()
        sheet.version += 1
        sheet.save(update_fields=["status", "locked_at", "version"])
        self._write_score_event(
            sheet, "hr.recruitment.score_sheet.locked", "LOCK", "评分表已封板"
        )
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
            self._write_score_event(
                sheet, "hr.recruitment.score_sheet.reopen_requested", "REOPEN_REQUEST", reason
            )
            return sheet
        if sheet.status == ScoreSheetStatus.REOPEN_REQUESTED and approve:
            sheet.status = ScoreSheetStatus.REOPEN_APPROVED
            sheet.reopened_by = approving_user or self.actor
            sheet.version += 1
            sheet.save(update_fields=["status", "reopened_by", "version"])
            self._write_score_event(
                sheet,
                "hr.recruitment.score_sheet.reopen_approved",
                "REOPEN_APPROVE",
                "评分解锁已批准",
            )
            return sheet
        if sheet.status == ScoreSheetStatus.REOPEN_APPROVED:
            sheet.status = ScoreSheetStatus.DRAFT
            sheet.version += 1
            sheet.save(update_fields=["status", "version"])
            self._write_score_event(
                sheet,
                "hr.recruitment.score_sheet.reopened",
                "REOPEN",
                "评分表回到草稿，新提交将生成新版本",
            )
            return sheet
        raise InvalidStateTransitionError(
            f"当前状态 {sheet.status} 不可解锁"
        )

    # ---- 结果快照 ----

    @transaction.atomic
    def freeze_result_snapshot(self, *, position_id: str) -> list[HrSelectionResultSnapshot]:
        """
        冻结选拔结果（§12.7/§24）：按服务端总分生成排名快照。

        规则：
        - 版本化：每次冻结生成新 snapshot_version，保留历史（不删旧快照）；
        - 同一组件多位评估人：先按候选对该组件取评估人平均，再按组件权重加权聚合；
        - 无 LOCKED 评分表 → 拒绝冻结（不产生空版本）。
        """
        position = HrRecruitmentPosition.objects.select_for_update().get(
            id=position_id, tenant_id=self.tenant_id
        )
        sheets = list(
            HrCandidateScoreSheet.objects.filter(
                tenant_id=self.tenant_id,
                application_id__recruitment_position_id_id=position_id,
                status=ScoreSheetStatus.LOCKED,
            ).select_related("application_id", "event_id", "event_id__component_id")
        )
        if not sheets:
            raise AssessmentServiceError(
                "NO_LOCKED_SCORES", "没有已锁定的评分结果，禁止冻结选拔排名", http_status=409
            )
        for sheet in sheets:
            self._verify_score_revision(sheet)

        # (application_id, component_id) → [sheet.total_score]（同一组件多位评估人）
        # sheet.total_score 已含组件权重（save_scores 中 raw/max×weight），此处不再重复乘权重
        app_component_scores: dict[tuple[str, str], list] = {}
        for sheet in sheets:
            app_id = str(sheet.application_id_id)
            component_id = str(sheet.event_id.component_id_id)
            app_component_scores.setdefault((app_id, component_id), []).append(sheet.total_score)

        # 按候选聚合：Σ(组件内评估人平均)（已含权重）
        app_totals: dict[str, Decimal] = {}
        for (app_id, _component_id), scores in app_component_scores.items():
            avg = sum(scores, Decimal(0)) / len(scores)
            app_totals[app_id] = app_totals.get(app_id, Decimal(0)) + avg

        # 新版本号（保留历史）
        last_version = (
            HrSelectionResultSnapshot.objects.filter(
                tenant_id=self.tenant_id, recruitment_position_id_id=position_id
            ).aggregate(max=Max("snapshot_version"))["max"]
            or 0
        )
        snapshot_version = last_version + 1

        snapshots = []
        # 排名：总分降序；并列时按 tie_break_rule_json 规则（§39 tie-break）
        # 支持 {"by": "submitted_at", "order": "asc"|"desc"}（V1 实现提交时间次级排序）
        from hr_recruitment.models import HrJobApplication

        tie_rule = position.scheme_tie_break_rule()
        by = (tie_rule or {}).get("by")
        order = (tie_rule or {}).get("order", "asc")
        apps_map = {
            str(a.id): a for a in HrJobApplication.objects.filter(
                tenant_id=self.tenant_id, id__in=list(app_totals.keys())
            )
        }

        def _sort_key(kv):
            # 主 key：总分（降序）；副 key：tie-break 字段
            app = apps_map.get(kv[0])
            if by == "submitted_at" and app and app.submitted_at:
                ts = app.submitted_at.timestamp()
                # reverse=True 时副 key 需取反以实现 asc 语义
                return (kv[1], -ts if order == "asc" else ts)
            return (kv[1], kv[0])

        ranked = sorted(app_totals.items(), key=_sort_key, reverse=True)
        for rank, (app_id, total) in enumerate(ranked, start=1):
            snapshots.append(
                HrSelectionResultSnapshot.objects.create(
                    tenant_id=self.tenant_id,
                    recruitment_position_id_id=position_id,
                    snapshot_version=snapshot_version,
                    rank=rank,
                    application_id_id=app_id,
                    final_score=total,
                    calculation_version=f"v{snapshot_version}",
                )
            )
        return snapshots
