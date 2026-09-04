"""Governed self-service objection and formal review workflow for HR12."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_assessment.models import (
    HrAssessmentCase,
    HrAssessmentObjection,
    HrFinalAssessmentResult,
    HrResultNotice,
)
from hr_assessment.services.result_correction_service import (
    AssessmentResultCorrectionError,
    AssessmentResultCorrectionService,
    ResultCorrectionInput,
    canonical_result_snapshot,
)


class AssessmentObjectionError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 409):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


class AssessmentObjectionService:
    DECISION_CODES = {"UPHELD", "MODIFIED", "REJECTED"}

    def __init__(self, tenant_id: int, actor_staff_id=None, correlation_id: str = ""):
        if not tenant_id:
            raise AssessmentObjectionError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required", status=403
            )
        self.tenant_id = int(tenant_id)
        self.actor_staff_id = actor_staff_id
        self.correlation_id = str(correlation_id or "")

    @transaction.atomic
    def submit(self, *, result_id, reason: str, evidence_refs=None) -> HrAssessmentObjection:
        result = HrFinalAssessmentResult.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            id=result_id,
        ).first()
        if result is None:
            raise AssessmentObjectionError(
                "ASSESSMENT_RESULT_NOT_FOUND", "未找到当前学校的正式考核结果", status=404
            )
        case = HrAssessmentCase.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            id=result.case_id,
        ).first()
        if case is None:
            raise AssessmentObjectionError(
                "ASSESSMENT_RESULT_CASE_NOT_FOUND", "正式结果缺少考核对象", status=404
            )
        if not self.actor_staff_id or str(case.staff_id) != str(self.actor_staff_id):
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_SELF_SCOPE_REQUIRED",
                "只有被考核本人可以提交结果异议",
                status=403,
            )
        current = canonical_result_snapshot(result)
        version = int(current.get("version") or 0)
        if version < 1 or str(current.get("status") or "").upper() == "REVOKED":
            raise AssessmentObjectionError(
                "ASSESSMENT_RESULT_VERSION_STATE_INVALID", "当前结果版本不可提出异议"
            )
        if not HrResultNotice.objects.filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=version,
            delivery_status="DELIVERED",
            delivered_at__isnull=False,
        ).exists():
            raise AssessmentObjectionError(
                "ASSESSMENT_RESULT_NOT_DELIVERED", "结果正式送达后方可提交异议"
            )
        reason = str(reason or "").strip()
        if len(reason) < 10 or len(reason) > 4000:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_REASON_INVALID",
                "异议理由应为 10—4000 个字符",
                status=400,
            )
        refs = [str(value).strip() for value in (evidence_refs or []) if str(value).strip()]
        if len(refs) > 20 or any(len(value) > 200 for value in refs):
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_EVIDENCE_INVALID",
                "证据引用最多 20 项且每项不超过 200 个字符",
                status=400,
            )
        existing = HrAssessmentObjection.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
            result_version=version,
        ).first()
        if existing is not None:
            if existing.reason == reason and existing.evidence_json == refs:
                return existing
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_ALREADY_OPEN", "当前结果版本已提交异议"
            )
        objection = HrAssessmentObjection.objects.create(
            tenant_id=self.tenant_id,
            result=result,
            result_version=version,
            submitted_by_staff_id=self.actor_staff_id,
            reason=reason,
            evidence_json=refs,
            status="SUBMITTED",
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_objection.submitted",
            payload={
                "resultId": str(result.id),
                "objectionId": str(objection.id),
                "resultVersion": version,
                "submittedByStaffId": str(self.actor_staff_id),
                "submittedAt": objection.submitted_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return objection

    @transaction.atomic
    def decide(
        self,
        *,
        objection_id,
        decision_code: str,
        conclusion: str,
        expected_version=None,
        changes=None,
    ) -> HrAssessmentObjection:
        objection = HrAssessmentObjection.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            id=objection_id,
        ).select_related("result").first()
        if objection is None:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_NOT_FOUND", "未找到当前学校的结果异议", status=404
            )
        decision = str(decision_code or "").strip().upper()
        if decision not in self.DECISION_CODES:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_DECISION_INVALID",
                "复核决定必须为异议成立、部分调整或驳回",
                status=400,
            )
        conclusion = str(conclusion or "").strip()
        if len(conclusion) < 10 or len(conclusion) > 4000:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_CONCLUSION_INVALID",
                "复核结论应为 10—4000 个字符",
                status=400,
            )
        if not self.actor_staff_id:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_REVIEWER_REQUIRED", "复核人员账号未关联教职工主档", status=403
            )
        if str(self.actor_staff_id) == str(objection.submitted_by_staff_id):
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_REVIEWER_CONFLICT", "异议提交人不得复核本人异议", status=403
            )
        if objection.status == "CLOSED":
            if (
                str(objection.reviewer_staff_id or "") != str(self.actor_staff_id)
                or objection.decision_code != decision
                or objection.conclusion != conclusion
            ):
                raise AssessmentObjectionError(
                    "ASSESSMENT_OBJECTION_IDEMPOTENCY_CONFLICT",
                    "该异议已经用另一份复核决定结案",
                )
            if decision in {"UPHELD", "MODIFIED"}:
                try:
                    replay_revision = AssessmentResultCorrectionService(
                        self.tenant_id,
                        actor_staff_id=self.actor_staff_id,
                        correlation_id=self.correlation_id,
                    ).append(
                        result_id=objection.result_id,
                        payload=ResultCorrectionInput(
                            correction_no=f"OBJ-{objection.id}",
                            expected_version=expected_version,
                            revision_type="CORRECTION",
                            reason=f"异议复核：{conclusion}",
                            changes=changes or {},
                        ),
                    )
                except AssessmentResultCorrectionError as exc:
                    raise AssessmentObjectionError(exc.code, str(exc)) from exc
                if str(replay_revision.id) != str(objection.resolution_revision_id or ""):
                    raise AssessmentObjectionError(
                        "ASSESSMENT_OBJECTION_IDEMPOTENCY_CONFLICT",
                        "该异议的正式更正记录与重放请求不一致",
                    )
            elif changes:
                raise AssessmentObjectionError(
                    "ASSESSMENT_OBJECTION_REJECT_CHANGES_FORBIDDEN",
                    "驳回异议时不得修改正式结果",
                    status=400,
                )
            return objection
        if objection.status not in {
            "SUBMITTED", "ACCEPTED_FOR_REVIEW", "RETURNED_FOR_MORE_INFO", "UNDER_REVIEW"
        }:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_INVALID_STATE", "当前异议状态不可复核结案"
            )
        revision = None
        if decision in {"UPHELD", "MODIFIED"}:
            try:
                revision = AssessmentResultCorrectionService(
                    self.tenant_id,
                    actor_staff_id=self.actor_staff_id,
                    correlation_id=self.correlation_id,
                ).append(
                    result_id=objection.result_id,
                    payload=ResultCorrectionInput(
                        correction_no=f"OBJ-{objection.id}",
                        expected_version=expected_version,
                        revision_type="CORRECTION",
                        reason=f"异议复核：{conclusion}",
                        changes=changes or {},
                    ),
                )
            except AssessmentResultCorrectionError as exc:
                raise AssessmentObjectionError(exc.code, str(exc)) from exc
        elif changes:
            raise AssessmentObjectionError(
                "ASSESSMENT_OBJECTION_REJECT_CHANGES_FORBIDDEN",
                "驳回异议时不得修改正式结果",
                status=400,
            )
        now = timezone.now()
        objection.reviewer_staff_id = self.actor_staff_id
        objection.conflict_check_json = {
            "checked": True,
            "submitterDifferentFromReviewer": True,
            "checkedAt": now.isoformat(),
        }
        objection.conclusion = conclusion
        objection.decision_code = decision
        objection.resolution_revision_id = revision.id if revision else None
        objection.status = "CLOSED"
        objection.resolved_at = now
        objection.save(update_fields=[
            "reviewer_staff_id", "conflict_check_json", "conclusion",
            "decision_code", "resolution_revision_id", "status", "resolved_at", "updated_at",
        ])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name="hr.assessment.assessment_objection.decided",
            payload={
                "resultId": str(objection.result_id),
                "objectionId": str(objection.id),
                "decisionCode": decision,
                "resolutionRevisionId": str(revision.id) if revision else None,
                "reviewerStaffId": str(self.actor_staff_id),
                "resolvedAt": now.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return objection
