"""Append-only corrections for sealed HR12 assessment results."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_assessment.authority_registry import (
    EVENT_RESULT_CORRECTED,
    EVENT_RESULT_REVOKED,
)
from hr_assessment.models.result import HrFinalAssessmentResult, HrResultRevision


class AssessmentResultCorrectionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ResultCorrectionInput:
    correction_no: str
    expected_version: int
    revision_type: str
    reason: str
    changes: dict


def base_result_snapshot(result: HrFinalAssessmentResult) -> dict:
    return {
        "sourceResultId": str(result.id),
        "sourceContentHash": result.content_hash,
        "version": int(result.result_version_no),
        "status": result.status,
        "gradeCode": result.grade_code,
        "displayGrade": result.display_grade_snapshot_json or {},
        "calculatedScore": (
            str(result.calculated_score) if result.calculated_score is not None else None
        ),
        "decisionReason": result.decision_reason or "",
    }


def canonical_result_snapshot(result: HrFinalAssessmentResult) -> dict:
    revision_manager = getattr(result, "revisions", None)
    if revision_manager is None:
        return base_result_snapshot(result)
    latest = revision_manager.order_by("-new_version", "-created_at").first()
    if latest is None:
        return base_result_snapshot(result)
    return copy.deepcopy(latest.after_snapshot_json or {})


class AssessmentResultCorrectionService:
    TYPES = {"CORRECTION", "REVOCATION"}
    CHANGE_FIELDS = {
        "gradeCode",
        "displayGrade",
        "calculatedScore",
        "decisionReason",
    }

    def __init__(self, tenant_id: int, actor_staff_id=None, correlation_id: str = ""):
        if not tenant_id:
            raise AssessmentResultCorrectionError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_staff_id = actor_staff_id
        self.correlation_id = str(correlation_id or "")

    @staticmethod
    def _normalize_changes(changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_CHANGES_INVALID", "changes must be an object"
            )
        unknown = set(changes) - AssessmentResultCorrectionService.CHANGE_FIELDS
        if unknown:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_CHANGE_FIELD_FORBIDDEN",
                f"unsupported correction fields: {', '.join(sorted(unknown))}",
            )
        normalized = copy.deepcopy(changes)
        if "gradeCode" in normalized:
            normalized["gradeCode"] = str(normalized["gradeCode"] or "").strip().upper()
            if not normalized["gradeCode"]:
                raise AssessmentResultCorrectionError(
                    "ASSESSMENT_GRADE_REQUIRED", "gradeCode cannot be empty"
                )
        if "displayGrade" in normalized and not isinstance(
            normalized["displayGrade"], dict
        ):
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_GRADE_SNAPSHOT_INVALID", "displayGrade must be an object"
            )
        if "calculatedScore" in normalized:
            raw = normalized["calculatedScore"]
            if raw in (None, ""):
                normalized["calculatedScore"] = None
            else:
                try:
                    normalized["calculatedScore"] = str(Decimal(str(raw)))
                except (InvalidOperation, ValueError):
                    raise AssessmentResultCorrectionError(
                        "ASSESSMENT_SCORE_INVALID", "calculatedScore must be numeric"
                    )
        if "decisionReason" in normalized:
            normalized["decisionReason"] = str(
                normalized["decisionReason"] or ""
            ).strip()
        return normalized

    @staticmethod
    def _apply(before: dict, revision_type: str, changes: dict) -> dict:
        after = copy.deepcopy(before)
        if revision_type == "CORRECTION":
            if not changes:
                raise AssessmentResultCorrectionError(
                    "ASSESSMENT_RESULT_CHANGES_REQUIRED",
                    "a correction must change at least one formal field",
                )
            after.update(changes)
            after["status"] = "CORRECTED"
        else:
            if changes:
                raise AssessmentResultCorrectionError(
                    "ASSESSMENT_RESULT_REVOCATION_CHANGES_FORBIDDEN",
                    "revocation cannot replace formal result fields",
                )
            after["status"] = "REVOKED"
        return after

    def _exact_replay(
        self,
        *,
        existing: HrResultRevision,
        result_id,
        payload: ResultCorrectionInput,
        normalized_changes: dict,
    ) -> HrResultRevision:
        expected_after = self._apply(
            existing.before_snapshot_json or {},
            payload.revision_type,
            normalized_changes,
        )
        expected_after["version"] = existing.new_version
        if (
            str(existing.result_id) != str(result_id)
            or existing.previous_version != payload.expected_version
            or existing.revision_type != payload.revision_type
            or existing.reason != payload.reason
            or (existing.after_snapshot_json or {}) != expected_after
        ):
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_CORRECTION_IDEMPOTENCY_CONFLICT",
                "correction_no already belongs to another payload",
            )
        return existing

    @transaction.atomic
    def append(
        self, *, result_id, payload: ResultCorrectionInput
    ) -> HrResultRevision:
        correction_no = str(payload.correction_no or "").strip()
        if not correction_no or len(correction_no) > 80:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_CORRECTION_NO_INVALID",
                "correctionNo is required and must not exceed 80 characters",
            )
        revision_type = str(payload.revision_type or "").strip().upper()
        if revision_type not in self.TYPES:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_REVISION_TYPE_INVALID",
                "revisionType must be CORRECTION or REVOCATION",
            )
        reason = str(payload.reason or "").strip()
        if not reason:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_CORRECTION_REASON_REQUIRED",
                "a correction/revocation reason is required",
            )
        try:
            expected_version = int(payload.expected_version)
        except (TypeError, ValueError):
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_EXPECTED_VERSION_INVALID",
                "expectedVersion must be a positive integer",
            )
        if expected_version < 1:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_EXPECTED_VERSION_INVALID",
                "expectedVersion must be a positive integer",
            )
        normalized_payload = ResultCorrectionInput(
            correction_no=correction_no,
            expected_version=expected_version,
            revision_type=revision_type,
            reason=reason,
            changes=payload.changes,
        )
        changes = self._normalize_changes(payload.changes)

        existing = HrResultRevision.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            correction_no=correction_no,
        ).first()
        if existing is not None:
            return self._exact_replay(
                existing=existing,
                result_id=result_id,
                payload=normalized_payload,
                normalized_changes=changes,
            )

        result = HrFinalAssessmentResult.objects.select_for_update().filter(
            id=result_id,
            tenant_id=self.tenant_id,
        ).first()
        if result is None:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_NOT_FOUND",
                "formal result not found inside tenant",
            )
        latest = HrResultRevision.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            result_id=result.id,
        ).order_by("-new_version", "-created_at").first()
        before = (
            copy.deepcopy(latest.after_snapshot_json or {})
            if latest is not None
            else base_result_snapshot(result)
        )
        current_version = (
            int(latest.new_version) if latest is not None else int(result.result_version_no)
        )
        if current_version != expected_version:
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_VERSION_CONFLICT",
                f"current version is {current_version}, not {expected_version}",
            )
        if before.get("status") == "REVOKED":
            raise AssessmentResultCorrectionError(
                "ASSESSMENT_RESULT_ALREADY_REVOKED",
                "a revoked result cannot receive more corrections",
            )
        after = self._apply(before, revision_type, changes)
        after["version"] = current_version + 1
        effective_at = timezone.now()
        revision = HrResultRevision.objects.create(
            tenant_id=self.tenant_id,
            result=result,
            correction_no=correction_no,
            previous_version=current_version,
            new_version=current_version + 1,
            revision_type=revision_type,
            reason=reason,
            authority_staff_id=self.actor_staff_id,
            before_snapshot_json=before,
            after_snapshot_json=after,
            effective_at=effective_at,
            sealed_at=effective_at,
        )
        event_name = (
            EVENT_RESULT_CORRECTED
            if revision_type == "CORRECTION"
            else EVENT_RESULT_REVOKED
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=event_name,
            payload={
                "resultId": str(result.id),
                "revisionId": str(revision.id),
                "correctionNo": revision.correction_no,
                "previousVersion": revision.previous_version,
                "newVersion": revision.new_version,
                "revisionType": revision.revision_type,
                "contentHash": revision.content_hash,
                "sealedAt": revision.sealed_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return revision
