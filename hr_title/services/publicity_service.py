"""HR13 publicity and appeal authority workflow."""

from __future__ import annotations

from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_title.models import (
    TitleAppealRecord,
    TitleApplicationCase,
    TitlePublicityRecord,
)


class TitlePublicityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class TitlePublicityService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise TitlePublicityError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> TitleApplicationCase:
        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise TitlePublicityError("TITLE_CASE_NOT_FOUND", "application case not found")
        return case

    def _lock_publicity(self, publicity_id) -> TitlePublicityRecord:
        publicity = (
            TitlePublicityRecord.objects.select_for_update()
            .filter(id=publicity_id, tenant_id=self.tenant_id)
            .first()
        )
        if publicity is None:
            raise TitlePublicityError("TITLE_PUBLICITY_NOT_FOUND", "publicity record not found")
        return publicity

    @transaction.atomic
    def open_publicity(
        self,
        *,
        case_id,
        publicity_no: str,
        start_at,
        end_at,
        content_snapshot=None,
    ) -> TitlePublicityRecord:
        case = self._lock_case(case_id)
        if case.status != TitleApplicationCase.Status.PROPOSED:
            raise TitlePublicityError(
                "TITLE_PUBLICITY_INVALID_CASE_STATE",
                f"case status {case.status} cannot enter publicity",
            )
        publicity_no = (publicity_no or "").strip()
        if not publicity_no:
            raise TitlePublicityError("TITLE_PUBLICITY_NO_REQUIRED", "publicity_no is required")
        if start_at is None or end_at is None or end_at <= start_at:
            raise TitlePublicityError(
                "TITLE_PUBLICITY_TIME_RANGE_INVALID",
                "end_at must be later than start_at",
            )
        if TitlePublicityRecord.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            application_case_id=case.id,
            status=TitlePublicityRecord.Status.OPEN,
        ).exists():
            raise TitlePublicityError(
                "TITLE_PUBLICITY_ALREADY_OPEN",
                "an open publicity record already exists for this case",
            )
        publicity = TitlePublicityRecord.objects.create(
            tenant_id=self.tenant_id,
            publicity_no=publicity_no,
            application_case_id=case.id,
            start_at=start_at,
            end_at=end_at,
            content_snapshot_json=content_snapshot or {},
            status=TitlePublicityRecord.Status.OPEN,
            opened_by=self.actor_user_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        case.status = TitleApplicationCase.Status.PUBLICITY
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return publicity

    @transaction.atomic
    def lodge_appeal(
        self,
        *,
        publicity_id,
        appeal_no: str,
        reason: str,
        appellant_ref: str = "",
        evidence=None,
    ) -> TitleAppealRecord:
        publicity = self._lock_publicity(publicity_id)
        if publicity.status != TitlePublicityRecord.Status.OPEN:
            raise TitlePublicityError(
                "TITLE_APPEAL_PUBLICITY_NOT_OPEN",
                "appeals can only be lodged while publicity is open",
            )
        if timezone.now() > publicity.end_at:
            raise TitlePublicityError(
                "TITLE_APPEAL_WINDOW_CLOSED",
                "the publicity appeal window has ended",
            )
        appeal_no = (appeal_no or "").strip()
        reason = (reason or "").strip()
        if not appeal_no or not reason:
            raise TitlePublicityError(
                "TITLE_APPEAL_CONTENT_REQUIRED",
                "appeal_no and reason are required",
            )
        return TitleAppealRecord.objects.create(
            tenant_id=self.tenant_id,
            appeal_no=appeal_no,
            publicity_id=publicity.id,
            application_case_id=publicity.application_case_id,
            appellant_ref=(appellant_ref or "").strip(),
            reason=reason,
            evidence_json=evidence or {},
            status=TitleAppealRecord.Status.OPEN,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def resolve_appeal(
        self,
        appeal_id,
        *,
        outcome: str,
        resolution: str,
    ) -> TitleAppealRecord:
        appeal = (
            TitleAppealRecord.objects.select_for_update()
            .filter(id=appeal_id, tenant_id=self.tenant_id)
            .first()
        )
        if appeal is None:
            raise TitlePublicityError("TITLE_APPEAL_NOT_FOUND", "appeal not found")
        if appeal.status != TitleAppealRecord.Status.OPEN:
            raise TitlePublicityError(
                "TITLE_APPEAL_ALREADY_RESOLVED",
                "only an open appeal can be resolved",
            )
        allowed = {
            TitleAppealRecord.Status.REJECTED,
            TitleAppealRecord.Status.UPHELD,
            TitleAppealRecord.Status.WITHDRAWN,
        }
        if outcome not in allowed:
            raise TitlePublicityError(
                "TITLE_APPEAL_OUTCOME_INVALID",
                "outcome must be REJECTED, UPHELD or WITHDRAWN",
            )
        resolution = (resolution or "").strip()
        if outcome != TitleAppealRecord.Status.WITHDRAWN and not resolution:
            raise TitlePublicityError(
                "TITLE_APPEAL_RESOLUTION_REQUIRED",
                "resolution is required for a reviewed appeal",
            )
        appeal.status = outcome
        appeal.resolution = resolution
        appeal.resolved_by = self.actor_user_id
        appeal.resolved_at = timezone.now()
        appeal.updated_by = self.actor_user_id
        appeal.save(
            update_fields=[
                "status",
                "resolution",
                "resolved_by",
                "resolved_at",
                "updated_by",
                "updated_at",
            ]
        )
        return appeal

    @transaction.atomic
    def close_publicity(self, publicity_id) -> TitlePublicityRecord:
        publicity = self._lock_publicity(publicity_id)
        if publicity.status != TitlePublicityRecord.Status.OPEN:
            raise TitlePublicityError(
                "TITLE_PUBLICITY_NOT_OPEN",
                "only an open publicity record can be closed",
            )
        if timezone.now() < publicity.end_at:
            raise TitlePublicityError(
                "TITLE_PUBLICITY_PERIOD_NOT_ENDED",
                "publicity cannot close before end_at",
            )
        appeals = TitleAppealRecord.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            publicity_id=publicity.id,
        )
        if appeals.filter(status=TitleAppealRecord.Status.OPEN).exists():
            raise TitlePublicityError(
                "TITLE_PUBLICITY_APPEALS_PENDING",
                "all appeals must be resolved before publicity can close",
            )
        if appeals.filter(status=TitleAppealRecord.Status.UPHELD).exists():
            raise TitlePublicityError(
                "TITLE_PUBLICITY_UPHELD_APPEAL",
                "an upheld appeal blocks publicity completion",
            )
        publicity.status = TitlePublicityRecord.Status.CLOSED
        publicity.closed_by = self.actor_user_id
        publicity.closed_at = timezone.now()
        publicity.updated_by = self.actor_user_id
        publicity.save(
            update_fields=[
                "status",
                "closed_by",
                "closed_at",
                "updated_by",
                "updated_at",
            ]
        )
        return publicity

    @transaction.atomic
    def cancel_publicity(self, publicity_id) -> TitlePublicityRecord:
        publicity = self._lock_publicity(publicity_id)
        if publicity.status != TitlePublicityRecord.Status.OPEN:
            raise TitlePublicityError(
                "TITLE_PUBLICITY_NOT_OPEN",
                "only an open publicity record can be cancelled",
            )
        case = self._lock_case(publicity.application_case_id)
        if case.status != TitleApplicationCase.Status.PUBLICITY:
            raise TitlePublicityError(
                "TITLE_PUBLICITY_CASE_STATE_MISMATCH",
                "case is no longer in publicity state",
            )
        publicity.status = TitlePublicityRecord.Status.CANCELLED
        publicity.cancelled_at = timezone.now()
        publicity.updated_by = self.actor_user_id
        publicity.save(
            update_fields=["status", "cancelled_at", "updated_by", "updated_at"]
        )
        case.status = TitleApplicationCase.Status.PROPOSED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return publicity
