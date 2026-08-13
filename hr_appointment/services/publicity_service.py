"""Publicity and objection workflow for HR14 appointment competitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentBatch,
    AppointmentPublicityObjection,
    AppointmentPublicityRecord,
    AppointmentRankingResult,
)


class AppointmentPublicityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PublicityOutcome:
    publicity: AppointmentPublicityRecord
    case: AppointmentApplicationCase
    created: bool


class AppointmentPublicityService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise AppointmentPublicityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _case(self, case_id, *, lock=False) -> AppointmentApplicationCase:
        qs = AppointmentApplicationCase.objects
        if lock:
            qs = qs.select_for_update()
        case = qs.filter(tenant_id=self.tenant_id, id=case_id).first()
        if case is None:
            raise AppointmentPublicityError(
                "APPOINTMENT_CASE_NOT_FOUND", "appointment application case not found"
            )
        return case

    def _publicity(self, publicity_id, *, lock=False) -> AppointmentPublicityRecord:
        qs = AppointmentPublicityRecord.objects
        if lock:
            qs = qs.select_for_update()
        record = qs.filter(tenant_id=self.tenant_id, id=publicity_id).first()
        if record is None:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_NOT_FOUND", "publicity record not found"
            )
        return record

    @transaction.atomic
    def open_publicity(
        self,
        *,
        case_id,
        ranking_result_id,
        publicity_no: str,
        start_at,
        end_at,
        notice_snapshot: Optional[dict] = None,
    ) -> PublicityOutcome:
        publicity_no = str(publicity_no or "").strip()
        if not publicity_no:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_NO_REQUIRED", "publicity_no is required"
            )
        if start_at is None or end_at is None or end_at <= start_at:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_RANGE_INVALID", "end_at must be later than start_at"
            )
        notice_snapshot = {} if notice_snapshot is None else notice_snapshot
        if not isinstance(notice_snapshot, dict):
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_SNAPSHOT_INVALID", "notice_snapshot must be an object"
            )

        case = self._case(case_id, lock=True)
        existing = AppointmentPublicityRecord.objects.filter(
            tenant_id=self.tenant_id, publicity_no=publicity_no
        ).first()
        if existing is not None:
            if (
                existing.application_case_id != case.id
                or existing.ranking_result_id != ranking_result_id
                or existing.start_at != start_at
                or existing.end_at != end_at
                or existing.notice_snapshot_json != notice_snapshot
            ):
                raise AppointmentPublicityError(
                    "APPOINTMENT_PUBLICITY_IDEMPOTENCY_CONFLICT",
                    "publicity_no already exists with different content",
                )
            return PublicityOutcome(existing, case, False)

        if case.status != AppointmentApplicationCase.Status.PROPOSED:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_INVALID_CASE_STATE",
                f"publicity requires PROPOSED case, got {case.status}",
            )

        ranking = (
            AppointmentRankingResult.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                id=ranking_result_id,
                application_case_id=case.id,
                outcome=AppointmentRankingResult.Outcome.SELECTED,
            )
            .first()
        )
        if ranking is None:
            raise AppointmentPublicityError(
                "APPOINTMENT_SELECTED_RANKING_REQUIRED",
                "a selected ranking result for this case is required",
            )

        batch = (
            AppointmentBatch.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, batch_no=case.batch_no)
            .first()
        )
        if batch is None:
            raise AppointmentPublicityError(
                "APPOINTMENT_BATCH_NOT_FOUND", "appointment batch not found"
            )
        if batch.status == AppointmentBatch.Status.RANKING:
            if AppointmentApplicationCase.objects.filter(
                tenant_id=self.tenant_id,
                batch_no=batch.batch_no,
                status=AppointmentApplicationCase.Status.UNDER_REVIEW,
            ).exists():
                raise AppointmentPublicityError(
                    "APPOINTMENT_BATCH_RANKING_INCOMPLETE",
                    "all under-review cases must have a ranking outcome before publicity",
                )
            batch.status = AppointmentBatch.Status.PROPOSED
        if batch.status not in {
            AppointmentBatch.Status.PROPOSED,
            AppointmentBatch.Status.PUBLICITY,
        }:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_INVALID_BATCH_STATE",
                f"publicity requires PROPOSED/PUBLICITY batch, got {batch.status}",
            )
        if batch.publicity_from is not None and batch.publicity_from != start_at:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_BATCH_WINDOW_MISMATCH",
                "publicity start does not match frozen batch publicity window",
            )
        if batch.publicity_to is not None and batch.publicity_to != end_at:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_BATCH_WINDOW_MISMATCH",
                "publicity end does not match frozen batch publicity window",
            )

        attempt_no = (
            AppointmentPublicityRecord.objects.filter(
                tenant_id=self.tenant_id,
                application_case_id=case.id,
            ).aggregate(v=Max("attempt_no"))["v"]
            or 0
        ) + 1
        record = AppointmentPublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no=publicity_no,
            application_case_id=case.id,
            ranking_result_id=ranking.id,
            batch_no=case.batch_no,
            person_id=case.person_id,
            position_instance_id=case.position_instance_id,
            attempt_no=attempt_no,
            start_at=start_at,
            end_at=end_at,
            notice_snapshot_json=notice_snapshot,
            status=AppointmentPublicityRecord.Status.OPEN,
            opened_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        case.status = AppointmentApplicationCase.Status.PUBLICITY
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        batch.status = AppointmentBatch.Status.PUBLICITY
        batch.publicity_from = start_at
        batch.publicity_to = end_at
        batch.updated_by = self.actor_user_id
        batch.save(
            update_fields=[
                "status",
                "publicity_from",
                "publicity_to",
                "updated_by",
                "updated_at",
            ]
        )
        return PublicityOutcome(record, case, True)

    @transaction.atomic
    def submit_objection(
        self,
        *,
        publicity_id,
        objection_no: str,
        content_summary: str,
        submitter_ref: str = "",
        evidence_refs: Optional[list] = None,
        now=None,
    ) -> AppointmentPublicityObjection:
        objection_no = str(objection_no or "").strip()
        content_summary = str(content_summary or "").strip()
        if not objection_no or not content_summary:
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_FIELDS_REQUIRED",
                "objection_no and content_summary are required",
            )
        evidence_refs = [] if evidence_refs is None else evidence_refs
        if not isinstance(evidence_refs, list):
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_EVIDENCE_INVALID", "evidence_refs must be a list"
            )
        record = self._publicity(publicity_id, lock=True)
        clock = now or timezone.now()
        if record.status != AppointmentPublicityRecord.Status.OPEN:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_NOT_OPEN", "objections require an open publicity record"
            )
        if clock < record.start_at or clock > record.end_at:
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_OUTSIDE_WINDOW",
                "objection must be submitted within the publicity window",
            )
        existing = AppointmentPublicityObjection.objects.filter(
            tenant_id=self.tenant_id, objection_no=objection_no
        ).first()
        if existing is not None:
            if (
                existing.publicity_id != record.id
                or existing.content_summary != content_summary
                or existing.submitter_ref != str(submitter_ref or "").strip()
                or existing.evidence_refs_json != evidence_refs
            ):
                raise AppointmentPublicityError(
                    "APPOINTMENT_OBJECTION_IDEMPOTENCY_CONFLICT",
                    "objection_no already exists with different content",
                )
            return existing
        return AppointmentPublicityObjection.objects.create(
            tenant_id=self.tenant_id,
            objection_no=objection_no,
            publicity_id=record.id,
            submitter_ref=str(submitter_ref or "").strip(),
            content_summary=content_summary,
            evidence_refs_json=evidence_refs,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def resolve_objection(
        self,
        objection_id,
        *,
        outcome: str,
        resolution_note: str,
    ) -> AppointmentPublicityObjection:
        outcome = str(outcome or "").strip().upper()
        note = str(resolution_note or "").strip()
        if outcome not in {
            AppointmentPublicityObjection.Status.UPHELD,
            AppointmentPublicityObjection.Status.NOT_UPHELD,
            AppointmentPublicityObjection.Status.WITHDRAWN,
        }:
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_OUTCOME_INVALID", f"unsupported outcome: {outcome}"
            )
        if outcome != AppointmentPublicityObjection.Status.WITHDRAWN and not note:
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_RESOLUTION_REQUIRED",
                "resolved objections require a resolution note",
            )
        objection = (
            AppointmentPublicityObjection.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=objection_id)
            .first()
        )
        if objection is None:
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_NOT_FOUND", "objection not found"
            )
        if objection.status not in {
            AppointmentPublicityObjection.Status.RECEIVED,
            AppointmentPublicityObjection.Status.UNDER_REVIEW,
        }:
            raise AppointmentPublicityError(
                "APPOINTMENT_OBJECTION_ALREADY_RESOLVED",
                f"objection is already {objection.status}",
            )
        objection.status = outcome
        objection.resolution_note = note
        objection.resolved_by = self.actor_user_id
        objection.resolved_at = timezone.now()
        objection.updated_by = self.actor_user_id
        objection.save(
            update_fields=[
                "status",
                "resolution_note",
                "resolved_by",
                "resolved_at",
                "updated_by",
                "updated_at",
            ]
        )
        return objection

    @transaction.atomic
    def close_publicity(self, publicity_id, *, now=None) -> AppointmentPublicityRecord:
        record = self._publicity(publicity_id, lock=True)
        clock = now or timezone.now()
        if record.status != AppointmentPublicityRecord.Status.OPEN:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_NOT_OPEN", "only open publicity can be closed"
            )
        if clock < record.end_at:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_WINDOW_NOT_ENDED",
                "publicity window has not ended",
            )
        objections = AppointmentPublicityObjection.objects.filter(
            tenant_id=self.tenant_id, publicity_id=record.id
        )
        if objections.filter(
            status__in=[
                AppointmentPublicityObjection.Status.RECEIVED,
                AppointmentPublicityObjection.Status.UNDER_REVIEW,
            ]
        ).exists():
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_OBJECTION_PENDING",
                "all objections must be resolved before publicity can close",
            )
        if objections.filter(status=AppointmentPublicityObjection.Status.UPHELD).exists():
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_UPHELD_OBJECTION",
                "upheld objection requires publicity cancellation and correction",
            )
        record.status = AppointmentPublicityRecord.Status.CLOSED
        record.closed_by = self.actor_user_id
        record.closed_at = clock
        record.updated_by = self.actor_user_id
        record.save(
            update_fields=["status", "closed_by", "closed_at", "updated_by", "updated_at"]
        )
        return record

    @transaction.atomic
    def cancel_publicity(self, publicity_id, *, reason: str) -> AppointmentPublicityRecord:
        reason = str(reason or "").strip()
        if not reason:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_CANCEL_REASON_REQUIRED", "cancellation reason is required"
            )
        record = self._publicity(publicity_id, lock=True)
        if record.status != AppointmentPublicityRecord.Status.OPEN:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_NOT_OPEN", "only open publicity can be cancelled"
            )
        case = self._case(record.application_case_id, lock=True)
        record.status = AppointmentPublicityRecord.Status.CANCELLED
        record.cancellation_reason = reason
        record.closed_by = self.actor_user_id
        record.closed_at = timezone.now()
        record.updated_by = self.actor_user_id
        record.save(
            update_fields=[
                "status",
                "cancellation_reason",
                "closed_by",
                "closed_at",
                "updated_by",
                "updated_at",
            ]
        )
        case.status = AppointmentApplicationCase.Status.PROPOSED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return record

    def assert_ready_for_effect(self, case_id) -> AppointmentPublicityRecord:
        self._case(case_id)
        record = (
            AppointmentPublicityRecord.objects.filter(
                tenant_id=self.tenant_id,
                application_case_id=case_id,
            )
            .order_by("-attempt_no", "-created_at")
            .first()
        )
        if record is None or record.status != AppointmentPublicityRecord.Status.CLOSED:
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_NOT_CLOSED",
                "formal appointment effect requires a closed publicity record",
            )
        objections = AppointmentPublicityObjection.objects.filter(
            tenant_id=self.tenant_id, publicity_id=record.id
        )
        if objections.filter(
            status__in=[
                AppointmentPublicityObjection.Status.RECEIVED,
                AppointmentPublicityObjection.Status.UNDER_REVIEW,
                AppointmentPublicityObjection.Status.UPHELD,
            ]
        ).exists():
            raise AppointmentPublicityError(
                "APPOINTMENT_PUBLICITY_OBJECTION_BLOCKS_EFFECT",
                "unresolved or upheld objection blocks formal appointment effect",
            )
        return record
