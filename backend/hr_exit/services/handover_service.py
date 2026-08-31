"""Handover checklist authority for HR16 exits."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_exit.models import ExitCase, ExitHandoverItem


class ExitHandoverError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class HandoverGate:
    configured_required: int
    completed_required: int
    waived_required: int
    pending_required: int

    @property
    def ready(self) -> bool:
        return self.configured_required > 0 and self.pending_required == 0


class ExitHandoverService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise ExitHandoverError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _case(self, case_id, *, lock: bool = False) -> ExitCase:
        qs = ExitCase.objects
        if lock:
            qs = qs.select_for_update()
        case = qs.filter(tenant_id=self.tenant_id, id=case_id).first()
        if case is None:
            raise ExitHandoverError("EXIT_CASE_NOT_FOUND", "exit case not found")
        return case

    @transaction.atomic
    def add_item(
        self,
        *,
        case_id,
        item_no: str,
        category_code: str,
        title: str,
        description: str = "",
        required: bool = True,
        owner_staff_id=None,
        due_date=None,
        supersedes_item_id=None,
    ) -> ExitHandoverItem:
        case = self._case(case_id, lock=True)
        if case.status not in {ExitCase.Status.APPROVED, ExitCase.Status.HANDOVER}:
            raise ExitHandoverError(
                "EXIT_HANDOVER_INVALID_CASE_STATE",
                f"handover items require APPROVED/HANDOVER case, got {case.status}",
            )
        item_no = str(item_no or "").strip()
        title = str(title or "").strip()
        category_code = str(category_code or "").strip()
        if not item_no or not title or not category_code:
            raise ExitHandoverError(
                "EXIT_HANDOVER_ITEM_FIELDS_REQUIRED",
                "item_no, category_code and title are required",
            )
        if ExitHandoverItem.objects.filter(
            tenant_id=self.tenant_id, item_no=item_no
        ).exists():
            raise ExitHandoverError(
                "EXIT_HANDOVER_ITEM_NO_CONFLICT", "item_no already exists"
            )
        if supersedes_item_id:
            prior = ExitHandoverItem.objects.filter(
                tenant_id=self.tenant_id,
                id=supersedes_item_id,
                case_id=case.id,
                status__in=[
                    ExitHandoverItem.Status.COMPLETED,
                    ExitHandoverItem.Status.WAIVED,
                ],
            ).first()
            if prior is None:
                raise ExitHandoverError(
                    "EXIT_HANDOVER_SUPERSEDED_ITEM_NOT_FOUND",
                    "superseded terminal handover item not found",
                )
        return ExitHandoverItem.objects.create(
            tenant_id=self.tenant_id,
            item_no=item_no,
            case_id=case.id,
            category_code=category_code,
            title=title,
            description=str(description or "").strip(),
            required=bool(required),
            owner_staff_id=owner_staff_id,
            due_date=due_date,
            supersedes_item_id=supersedes_item_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def complete(self, item_id, *, evidence_ref: str = "") -> ExitHandoverItem:
        item = (
            ExitHandoverItem.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=item_id)
            .first()
        )
        if item is None:
            raise ExitHandoverError("EXIT_HANDOVER_ITEM_NOT_FOUND", "handover item not found")
        if item.status != ExitHandoverItem.Status.PENDING:
            raise ExitHandoverError(
                "EXIT_HANDOVER_ITEM_ALREADY_TERMINAL",
                f"handover item is already {item.status}",
            )
        case = self._case(item.case_id, lock=True)
        if case.status != ExitCase.Status.HANDOVER:
            raise ExitHandoverError(
                "EXIT_HANDOVER_INVALID_CASE_STATE",
                f"completion requires HANDOVER case, got {case.status}",
            )
        item.status = ExitHandoverItem.Status.COMPLETED
        item.evidence_ref = str(evidence_ref or "").strip()
        item.completed_by = self.actor_user_id
        item.completed_at = timezone.now()
        item.updated_by = self.actor_user_id
        item.save(
            update_fields=[
                "status",
                "evidence_ref",
                "completed_by",
                "completed_at",
                "updated_by",
                "updated_at",
            ]
        )
        return item

    @transaction.atomic
    def waive(self, item_id, *, reason: str) -> ExitHandoverItem:
        reason = str(reason or "").strip()
        if not reason:
            raise ExitHandoverError(
                "EXIT_HANDOVER_WAIVER_REASON_REQUIRED", "waiver reason is required"
            )
        item = (
            ExitHandoverItem.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=item_id)
            .first()
        )
        if item is None:
            raise ExitHandoverError("EXIT_HANDOVER_ITEM_NOT_FOUND", "handover item not found")
        if item.status != ExitHandoverItem.Status.PENDING:
            raise ExitHandoverError(
                "EXIT_HANDOVER_ITEM_ALREADY_TERMINAL",
                f"handover item is already {item.status}",
            )
        case = self._case(item.case_id, lock=True)
        if case.status != ExitCase.Status.HANDOVER:
            raise ExitHandoverError(
                "EXIT_HANDOVER_INVALID_CASE_STATE",
                f"waiver requires HANDOVER case, got {case.status}",
            )
        item.status = ExitHandoverItem.Status.WAIVED
        item.waiver_reason = reason
        item.completed_by = self.actor_user_id
        item.completed_at = timezone.now()
        item.updated_by = self.actor_user_id
        item.save(
            update_fields=[
                "status",
                "waiver_reason",
                "completed_by",
                "completed_at",
                "updated_by",
                "updated_at",
            ]
        )
        return item

    def gate(self, case_id) -> HandoverGate:
        self._case(case_id)
        required = ExitHandoverItem.objects.filter(
            tenant_id=self.tenant_id,
            case_id=case_id,
            required=True,
        )
        configured = required.count()
        completed = required.filter(status=ExitHandoverItem.Status.COMPLETED).count()
        waived = required.filter(status=ExitHandoverItem.Status.WAIVED).count()
        pending = required.filter(status=ExitHandoverItem.Status.PENDING).count()
        return HandoverGate(configured, completed, waived, pending)

    def assert_ready_for_settlement(self, case_id) -> HandoverGate:
        gate = self.gate(case_id)
        if gate.configured_required == 0:
            raise ExitHandoverError(
                "EXIT_HANDOVER_CHECKLIST_REQUIRED",
                "at least one required handover item must be configured before settlement",
            )
        if gate.pending_required:
            raise ExitHandoverError(
                "EXIT_HANDOVER_INCOMPLETE",
                f"{gate.pending_required} required handover item(s) are still pending",
            )
        return gate
