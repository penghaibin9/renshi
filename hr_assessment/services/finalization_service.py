"""HR12 formal assessment finalization boundary.

Formal results are append-only. Finalization is fail-closed over the current
provider snapshot, evidence/metric quality, reviewer submissions, decision
agenda scope and publicity completion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import models, transaction
from django.utils import timezone

from hr_assessment.models import (
    HrAssessmentCase,
    HrAssessmentDecisionSession,
    HrAssessmentEvidenceRef,
    HrAssessmentPolicyVersion,
    HrAssessmentPublicityCase,
    HrCycleSnapshot,
    HrFinalAssessmentResult,
    HrMetricSnapshot,
    HrProviderSnapshotSet,
    HrResultRuleVersion,
    HrReviewerAssignment,
)
from hr_assessment.service.evidence import EvidenceSnapshotError, PolicyEvidenceResolver


class AssessmentFinalizationError(Exception):
    def __init__(self, code: str, message: str, blockers=None):
        self.code = code
        self.blockers = blockers or []
        super().__init__(message)


@dataclass(frozen=True)
class FinalResultInput:
    decision_reason: str
    decision_session_id: object


@dataclass(frozen=True)
class CalculatedAssessmentResult:
    grade_code: str
    display_grade_snapshot: dict
    calculated_score: Decimal
    calculation_snapshot: dict


class AssessmentFinalizationService:
    CASE_ALLOWED = {"PROPOSED", "PUBLICITY"}
    DECISION_COMPLETE = {"COMPLETED", "CLOSED", "FINALIZED"}
    EVIDENCE_BLOCKING = {
        "PENDING",
        "PARTIALLY_VERIFIED",
        "SOURCE_UNAVAILABLE",
        "CONFLICT",
    }
    METRIC_BLOCKING = {"STALE", "UNAVAILABLE", "CONFLICT"}
    SCORE_AGGREGATIONS = {"AVERAGE", "WEIGHTED_AVERAGE"}

    def __init__(self, tenant_id: int, actor_staff_id=None):
        if not tenant_id:
            raise AssessmentFinalizationError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = tenant_id
        self.actor_staff_id = actor_staff_id

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _provider_snapshot_blockers(self, *, case: HrAssessmentCase) -> list[dict]:
        snapshot_set_id = getattr(case, "provider_snapshot_set_id", None)
        if not snapshot_set_id:
            return [{"code": "ASSESSMENT_PROVIDER_SNAPSHOT_REQUIRED"}]

        snapshot_set = HrProviderSnapshotSet.objects.filter(
            id=snapshot_set_id,
            tenant_id=self.tenant_id,
            case_id=case.id,
        ).first()
        if snapshot_set is None:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_STATE_DRIFT",
                    "snapshotSetId": str(snapshot_set_id),
                }
            ]
        if snapshot_set.status != "READY":
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_BLOCKED",
                    "snapshotSetId": str(snapshot_set.id),
                    "status": snapshot_set.status,
                    "providerStatus": snapshot_set.provider_status_json,
                }
            ]

        authority = snapshot_set.authority_json or {}
        if not authority:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_AUTHORITY_REQUIRED",
                    "snapshotSetId": str(snapshot_set.id),
                }
            ]
        try:
            plan = PolicyEvidenceResolver(self.tenant_id).resolve_case(case.id)
        except EvidenceSnapshotError as exc:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_AUTHORITY_REQUIRED",
                    "snapshotSetId": str(snapshot_set.id),
                    "reasonCode": exc.code,
                    "reason": str(exc),
                }
            ]

        drift: dict = {}
        if authority != plan.authority:
            drift["authority"] = {
                "snapshot": authority,
                "expected": plan.authority,
            }
        if list(snapshot_set.required_providers_json or []) != list(plan.required_providers):
            drift["requiredProviders"] = {
                "snapshot": list(snapshot_set.required_providers_json or []),
                "expected": list(plan.required_providers),
            }
        if snapshot_set.as_of != plan.as_of:
            drift["asOf"] = {
                "snapshot": snapshot_set.as_of.isoformat(),
                "expected": plan.as_of.isoformat(),
            }
        if drift:
            return [
                {
                    "code": "ASSESSMENT_PROVIDER_SNAPSHOT_AUTHORITY_DRIFT",
                    "snapshotSetId": str(snapshot_set.id),
                    "drift": drift,
                }
            ]
        return []

    def _gate_blockers(self, *, case: HrAssessmentCase, decision_session_id) -> list[dict]:
        blockers: list[dict] = []
        blockers.extend(self._provider_snapshot_blockers(case=case))

        unresolved_evidence = HrAssessmentEvidenceRef.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
            status__in=self.EVIDENCE_BLOCKING,
        ).count()
        if unresolved_evidence:
            blockers.append(
                {
                    "code": "ASSESSMENT_EVIDENCE_UNRESOLVED",
                    "count": unresolved_evidence,
                }
            )

        unresolved_metrics = HrMetricSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
            status__in=self.METRIC_BLOCKING,
        ).count()
        if unresolved_metrics:
            blockers.append(
                {
                    "code": "ASSESSMENT_METRIC_UNAVAILABLE",
                    "count": unresolved_metrics,
                }
            )

        assignments = HrReviewerAssignment.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
        ).prefetch_related("evaluations")
        if not assignments.exists():
            blockers.append({"code": "ASSESSMENT_REVIEWER_ASSIGNMENT_REQUIRED"})
        reviewer_missing = 0
        for assignment in assignments:
            if not assignment.evaluations.filter(submitted_at__isnull=False).exists():
                reviewer_missing += 1
        if reviewer_missing:
            blockers.append(
                {
                    "code": "ASSESSMENT_REVIEWER_SUBMISSION_MISSING",
                    "count": reviewer_missing,
                }
            )

        decision = HrAssessmentDecisionSession.objects.filter(
            id=decision_session_id,
            tenant_id=self.tenant_id,
            cycle_id=case.cycle_id,
        ).first()
        if decision is None:
            blockers.append({"code": "ASSESSMENT_DECISION_SESSION_REQUIRED"})
        elif decision.status not in self.DECISION_COMPLETE:
            blockers.append(
                {
                    "code": "ASSESSMENT_DECISION_SESSION_INCOMPLETE",
                    "status": decision.status,
                }
            )
        else:
            case_refs = {str(value) for value in (decision.case_refs_json or [])}
            if str(case.id) not in case_refs:
                blockers.append(
                    {
                        "code": "ASSESSMENT_DECISION_CASE_NOT_INCLUDED",
                        "decisionSessionId": str(decision.id),
                    }
                )

        if case.status == "PUBLICITY":
            publicity_done = HrAssessmentPublicityCase.objects.filter(
                tenant_id=self.tenant_id,
                cycle_id=case.cycle_id,
                status="COMPLETED",
                completed_at__isnull=False,
            ).exists()
            if not publicity_done:
                blockers.append({"code": "ASSESSMENT_PUBLICITY_INCOMPLETE"})

        return blockers

    @staticmethod
    def _decimal(value, *, code: str, message: str) -> Decimal:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AssessmentFinalizationError(code, message) from exc
        if not number.is_finite():
            raise AssessmentFinalizationError(code, message)
        return number

    @staticmethod
    def _grade_bands(mapping) -> list[dict]:
        if isinstance(mapping, dict) and isinstance(mapping.get("bands"), list):
            return list(mapping["bands"])
        if isinstance(mapping, list):
            return list(mapping)
        if isinstance(mapping, dict):
            bands = []
            for grade_code, spec in mapping.items():
                if not isinstance(spec, dict):
                    continue
                bands.append({"gradeCode": grade_code, **spec})
            return bands
        return []

    def _calculate_result(self, *, case: HrAssessmentCase) -> CalculatedAssessmentResult:
        """Derive the formal score and grade only from frozen, submitted facts."""

        if case.cycle_id is None or case.policy_version_id is None:
            raise AssessmentFinalizationError(
                "ASSESSMENT_CALCULATION_AUTHORITY_REQUIRED",
                "cycle and policy authority are required for server-side calculation",
            )
        cycle = case.cycle
        as_of = cycle.end_at.date()
        policy = HrAssessmentPolicyVersion.objects.filter(
            id=case.policy_version_id,
            tenant_id=self.tenant_id,
            status="PUBLISHED",
            effective_from__lte=as_of,
        ).filter(
            models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=as_of)
        ).first()
        if policy is None or not policy.result_rule_version_id:
            raise AssessmentFinalizationError(
                "ASSESSMENT_EFFECTIVE_RESULT_RULE_REQUIRED",
                "a published effective assessment policy with a result rule is required",
            )
        result_rule = HrResultRuleVersion.objects.filter(
            id=policy.result_rule_version_id,
            tenant_id=self.tenant_id,
            status="PUBLISHED",
        ).first()
        if result_rule is None:
            raise AssessmentFinalizationError(
                "ASSESSMENT_EFFECTIVE_RESULT_RULE_REQUIRED",
                "the policy result rule is missing or not published",
            )
        snapshot = HrCycleSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            cycle_id=case.cycle_id,
        ).first()
        if snapshot is None:
            raise AssessmentFinalizationError(
                "ASSESSMENT_CYCLE_SNAPSHOT_REQUIRED",
                "the frozen cycle calculation snapshot is required",
            )

        reviewer_rule = snapshot.frozen_reviewer_rules_json or {}
        aggregation = str(reviewer_rule.get("scoreAggregation") or "").upper()
        score_field = str(reviewer_rule.get("scoreField") or "").strip()
        if aggregation not in self.SCORE_AGGREGATIONS or not score_field:
            raise AssessmentFinalizationError(
                "ASSESSMENT_SCORE_RULE_INVALID",
                "frozen reviewer rules must define scoreAggregation and scoreField",
            )
        role_weights = reviewer_rule.get("roleWeights") or {}
        if aggregation == "WEIGHTED_AVERAGE" and not isinstance(role_weights, dict):
            raise AssessmentFinalizationError(
                "ASSESSMENT_SCORE_RULE_INVALID", "roleWeights must be an object"
            )

        assignments = list(
            HrReviewerAssignment.objects.filter(
                tenant_id=self.tenant_id,
                case_id=case.id,
            ).order_by("id")
        )
        if not assignments:
            raise AssessmentFinalizationError(
                "ASSESSMENT_REVIEWER_ASSIGNMENT_REQUIRED",
                "at least one reviewer assignment is required",
            )
        contributions = []
        weighted_sum = Decimal("0")
        total_weight = Decimal("0")
        for assignment in assignments:
            evaluation = assignment.evaluations.filter(
                tenant_id=self.tenant_id,
                submitted_at__isnull=False,
            ).order_by("-revision_no", "-submitted_at", "-id").first()
            if evaluation is None:
                raise AssessmentFinalizationError(
                    "ASSESSMENT_REVIEWER_SUBMISSION_MISSING",
                    "every reviewer assignment must have a submitted evaluation",
                )
            rating = evaluation.rating_json or {}
            if not isinstance(rating, dict) or score_field not in rating:
                raise AssessmentFinalizationError(
                    "ASSESSMENT_REVIEWER_SCORE_REQUIRED",
                    f"submitted evaluation must contain {score_field}",
                )
            score = self._decimal(
                rating[score_field],
                code="ASSESSMENT_REVIEWER_SCORE_INVALID",
                message="submitted reviewer score must be numeric",
            )
            weight = Decimal("1")
            if aggregation == "WEIGHTED_AVERAGE":
                if assignment.reviewer_role not in role_weights:
                    raise AssessmentFinalizationError(
                        "ASSESSMENT_REVIEWER_WEIGHT_REQUIRED",
                        f"missing frozen weight for reviewer role {assignment.reviewer_role}",
                    )
                weight = self._decimal(
                    role_weights[assignment.reviewer_role],
                    code="ASSESSMENT_REVIEWER_WEIGHT_INVALID",
                    message="reviewer role weight must be numeric",
                )
                if weight <= 0:
                    raise AssessmentFinalizationError(
                        "ASSESSMENT_REVIEWER_WEIGHT_INVALID",
                        "reviewer role weight must be positive",
                    )
            weighted_sum += score * weight
            total_weight += weight
            contributions.append(
                {
                    "assignmentId": str(assignment.id),
                    "evaluationId": str(evaluation.id),
                    "revisionNo": evaluation.revision_no,
                    "role": assignment.reviewer_role,
                    "score": str(score),
                    "weight": str(weight),
                    "submittedAt": evaluation.submitted_at.isoformat(),
                }
            )
        if total_weight <= 0:
            raise AssessmentFinalizationError(
                "ASSESSMENT_SCORE_RULE_INVALID", "total reviewer weight must be positive"
            )
        score = (weighted_sum / total_weight).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        rating_scale = snapshot.frozen_rating_scale_json or {}
        if not isinstance(rating_scale, dict):
            raise AssessmentFinalizationError(
                "ASSESSMENT_RATING_SCALE_INVALID", "frozen rating scale must be an object"
            )
        minimum = self._decimal(
            rating_scale.get("minValue"),
            code="ASSESSMENT_RATING_SCALE_INVALID",
            message="frozen rating scale minValue is required",
        )
        maximum = self._decimal(
            rating_scale.get("maxValue"),
            code="ASSESSMENT_RATING_SCALE_INVALID",
            message="frozen rating scale maxValue is required",
        )
        if minimum > maximum or not minimum <= score <= maximum:
            raise AssessmentFinalizationError(
                "ASSESSMENT_SCORE_OUT_OF_RANGE",
                "calculated score is outside the frozen rating scale",
            )

        matches = []
        for band in self._grade_bands(result_rule.score_to_grade_mapping):
            if not isinstance(band, dict):
                continue
            grade_code = str(band.get("gradeCode") or "").strip().upper()
            if not grade_code or "minScore" not in band or "maxScore" not in band:
                continue
            lower = self._decimal(
                band["minScore"],
                code="ASSESSMENT_RESULT_RULE_INVALID",
                message="grade band minScore must be numeric",
            )
            upper = self._decimal(
                band["maxScore"],
                code="ASSESSMENT_RESULT_RULE_INVALID",
                message="grade band maxScore must be numeric",
            )
            if lower <= score <= upper:
                matches.append((grade_code, band))
        if len(matches) != 1:
            raise AssessmentFinalizationError(
                "ASSESSMENT_RESULT_RULE_NO_UNIQUE_MATCH",
                "calculated score must match exactly one published grade band",
            )
        grade_code, band = matches[0]
        display_grade = band.get("displayGrade")
        if not isinstance(display_grade, dict) or not display_grade:
            label = str(band.get("label") or "").strip()
            display_grade = {"zh-CN": label} if label else {}
        if not display_grade:
            raise AssessmentFinalizationError(
                "ASSESSMENT_RESULT_RULE_INVALID",
                "matched grade band must define a display label",
            )
        calculation_snapshot = {
            "source": "SUBMITTED_REVIEWER_EVALUATIONS",
            "policyVersionId": str(policy.id),
            "resultRuleVersionId": str(result_rule.id),
            "cycleSnapshotId": str(snapshot.id),
            "scoreAggregation": aggregation,
            "scoreField": score_field,
            "contributions": contributions,
        }
        return CalculatedAssessmentResult(
            grade_code=grade_code,
            display_grade_snapshot=display_grade,
            calculated_score=score,
            calculation_snapshot=calculation_snapshot,
        )

    @transaction.atomic
    def finalize(self, *, case_id, payload: FinalResultInput) -> HrFinalAssessmentResult:
        case = HrAssessmentCase.objects.select_for_update().filter(
            id=case_id,
            tenant_id=self.tenant_id,
        ).first()
        if case is None:
            raise AssessmentFinalizationError(
                "ASSESSMENT_CASE_NOT_FOUND", "assessment case not found inside tenant"
            )

        if case.status == "FINALIZED":
            existing = HrFinalAssessmentResult.objects.filter(
                tenant_id=self.tenant_id,
                case_id=case.id,
            ).first()
            if existing is None:
                raise AssessmentFinalizationError(
                    "ASSESSMENT_RESULT_STATE_DRIFT",
                    "case is FINALIZED but no formal result exists",
                )
            return existing

        if case.status not in self.CASE_ALLOWED:
            raise AssessmentFinalizationError(
                "ASSESSMENT_CASE_INVALID_STATE",
                f"case status {case.status} cannot be finalized",
            )
        if not str(payload.decision_session_id or "").strip():
            raise AssessmentFinalizationError(
                "ASSESSMENT_DECISION_SESSION_REQUIRED",
                "decision_session_id is required",
            )

        blockers = self._gate_blockers(
            case=case,
            decision_session_id=payload.decision_session_id,
        )
        if blockers:
            raise AssessmentFinalizationError(
                "ASSESSMENT_FINALIZATION_BLOCKED",
                "assessment finalization gate contains blockers",
                blockers=blockers,
            )

        existing = HrFinalAssessmentResult.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            case_id=case.id,
        ).first()
        if existing is not None:
            raise AssessmentFinalizationError(
                "ASSESSMENT_RESULT_ALREADY_EXISTS",
                "formal result already exists; use revision workflow",
            )

        calculated = self._calculate_result(case=case)

        finalized_at = timezone.now()
        content = {
            "tenantId": int(self.tenant_id),
            "caseId": str(case.id),
            "assessmentType": case.assessment_type,
            "cycleId": str(case.cycle_id) if case.cycle_id else None,
            "gradeCode": calculated.grade_code,
            "displayGrade": calculated.display_grade_snapshot,
            "calculatedScore": str(calculated.calculated_score),
            "decisionReason": payload.decision_reason,
            "policyVersionId": str(case.policy_version_id) if case.policy_version_id else None,
            "decisionSessionId": str(payload.decision_session_id),
            "finalizedAt": finalized_at.isoformat(),
            "finalizedBy": (
                str(self.actor_staff_id) if self.actor_staff_id else None
            ),
            "resultVersionNo": 1,
            "status": "FINALIZED",
        }
        result = HrFinalAssessmentResult.objects.create(
            tenant_id=self.tenant_id,
            case_id=case.id,
            assessment_type=case.assessment_type,
            cycle_id=case.cycle_id,
            grade_code=calculated.grade_code,
            display_grade_snapshot_json=calculated.display_grade_snapshot,
            calculated_score=calculated.calculated_score,
            decision_reason=payload.decision_reason,
            policy_version_id=case.policy_version_id,
            decision_session_id=payload.decision_session_id,
            finalized_at=finalized_at,
            sealed_at=finalized_at,
            finalized_by=self.actor_staff_id,
            result_version_no=1,
            content_hash=self._hash_payload(content),
            status="FINALIZED",
        )

        case.status = "FINALIZED"
        case.save(update_fields=["status", "updated_at"])
        return result
