"""HR13 title application lifecycle authority service.

Application workflow is deliberately separate from the formal result fact chain.
RETURN is a correction loop, REJECT is a terminal eligibility decision, and
PUBLICITY is the only state from which ``ProfessionalTitleResultService`` may
create a formal title result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_title.models import TitleApplicationCase


class TitleApplicationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TitleApplicationInput:
    case_no: str
    person_id: object
    policy_version_id: object
    batch_no: str
    requested_title_code: str
    requested_title_name: str = ""


class TitleApplicationService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise TitleApplicationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> TitleApplicationCase:
        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise TitleApplicationError("TITLE_CASE_NOT_FOUND", "application case not found")
        return case

    def _transition(self, case: TitleApplicationCase, *, allowed_from, target: str):
        if case.status not in allowed_from:
            raise TitleApplicationError(
                "TITLE_CASE_INVALID_STATE",
                f"cannot transition title case from {case.status} to {target}",
            )
        case.status = target
        case.updated_by = self.actor_user_id
        update_fields = ["status", "updated_by", "updated_at"]
        if target == TitleApplicationCase.Status.SUBMITTED:
            case.submitted_at = timezone.now()
            update_fields.insert(1, "submitted_at")
        case.save(update_fields=update_fields)
        return case

    @transaction.atomic
    def create_draft(self, payload: TitleApplicationInput) -> TitleApplicationCase:
        if not payload.case_no.strip() or not payload.batch_no.strip():
            raise TitleApplicationError(
                "TITLE_CASE_IDENTITY_REQUIRED",
                "case_no and batch_no are required",
            )
        if not payload.requested_title_code.strip():
            raise TitleApplicationError(
                "TITLE_CODE_REQUIRED",
                "requested_title_code is required",
            )
        return TitleApplicationCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=payload.case_no.strip(),
            person_id=payload.person_id,
            policy_version_id=payload.policy_version_id,
            batch_no=payload.batch_no.strip(),
            requested_title_code=payload.requested_title_code.strip(),
            requested_title_name=payload.requested_title_name.strip(),
            status=TitleApplicationCase.Status.DRAFT,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def submit(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={
                TitleApplicationCase.Status.DRAFT,
                TitleApplicationCase.Status.RETURNED,
            },
            target=TitleApplicationCase.Status.SUBMITTED,
        )

    @transaction.atomic
    def return_for_correction(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={TitleApplicationCase.Status.SUBMITTED},
            target=TitleApplicationCase.Status.RETURNED,
        )

    @transaction.atomic
    def pass_eligibility(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={TitleApplicationCase.Status.SUBMITTED},
            target=TitleApplicationCase.Status.ELIGIBLE,
        )

    @transaction.atomic
    def reject_eligibility(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={TitleApplicationCase.Status.SUBMITTED},
            target=TitleApplicationCase.Status.REJECTED,
        )

    @transaction.atomic
    def withdraw(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={
                TitleApplicationCase.Status.DRAFT,
                TitleApplicationCase.Status.RETURNED,
                TitleApplicationCase.Status.SUBMITTED,
            },
            target=TitleApplicationCase.Status.WITHDRAWN,
        )

    @transaction.atomic
    def start_review(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={TitleApplicationCase.Status.ELIGIBLE},
            target=TitleApplicationCase.Status.UNDER_REVIEW,
        )

    @transaction.atomic
    def propose(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={TitleApplicationCase.Status.UNDER_REVIEW},
            target=TitleApplicationCase.Status.PROPOSED,
        )

    @transaction.atomic
    def enter_publicity(self, case_id) -> TitleApplicationCase:
        case = self._lock_case(case_id)
        return self._transition(
            case,
            allowed_from={TitleApplicationCase.Status.PROPOSED},
            target=TitleApplicationCase.Status.PUBLICITY,
        )
