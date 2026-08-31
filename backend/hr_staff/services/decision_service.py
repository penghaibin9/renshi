"""HR03 PersonnelDecision + reward/disciplinary Authority services."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from django.db import IntegrityError, transaction

from hr_staff.authority_registry import (
    EVENT_PERSONNEL_DECISION_EFFECTIVE,
    EVENT_REWARD_DISCIPLINARY_EFFECTIVE,
)
from hr_staff.models import (
    HrPersonnelDecision,
    HrRewardDisciplinaryCase,
    HrStaffMaster,
)
from hr_staff.services import outbox_service


class PersonnelAuthorityError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PersonnelAuthorityService:
    def __init__(
        self,
        tenant_id: int,
        *,
        actor_user_id: Optional[int] = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise PersonnelAuthorityError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    def _staff(self, staff_id) -> HrStaffMaster:
        staff = HrStaffMaster.objects.filter(
            id=staff_id, tenant_id=self.tenant_id
        ).first()
        if staff is None:
            raise PersonnelAuthorityError(
                "STAFF_NOT_FOUND", "staff not found inside tenant"
            )
        return staff

    def _decision(self, decision_id) -> HrPersonnelDecision:
        decision = HrPersonnelDecision.objects.filter(
            id=decision_id, tenant_id=self.tenant_id
        ).first()
        if decision is None:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_NOT_FOUND",
                "personnel decision not found inside tenant",
            )
        return decision

    def _locked_decision(self, decision_id) -> HrPersonnelDecision:
        decision = (
            HrPersonnelDecision.objects.select_for_update()
            .filter(id=decision_id, tenant_id=self.tenant_id)
            .first()
        )
        if decision is None:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_NOT_FOUND",
                "personnel decision not found inside tenant",
            )
        return decision

    @staticmethod
    def _validate_effective_range(
        effective_from: date, effective_to: Optional[date]
    ) -> None:
        if not effective_from:
            raise PersonnelAuthorityError(
                "EFFECTIVE_DATE_INVALID", "effective_from is required"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise PersonnelAuthorityError(
                "EFFECTIVE_DATE_INVALID",
                "effective_to must be later than effective_from",
            )

    @staticmethod
    def _decision_identity(decision: HrPersonnelDecision):
        return (
            str(decision.staff_id),
            decision.decision_type,
            decision.decision_action,
            decision.title,
            decision.basis_text,
            decision.content_snapshot_json,
            decision.decided_at,
            decision.effective_from,
            decision.effective_to,
            str(decision.supersedes_decision_id or ""),
            decision.correction_reason,
            decision.correction_evidence_ref,
            decision.source_business_type,
            decision.source_business_id,
        )

    @transaction.atomic
    def create_effective_decision(
        self,
        *,
        decision_no: str,
        staff_id,
        decision_type: str,
        title: str,
        content_snapshot: dict,
        decided_at: datetime,
        effective_from: date,
        effective_to: Optional[date] = None,
        decision_action: str = HrPersonnelDecision.DecisionAction.ISSUE,
        basis_text: str = "",
        supersedes_decision_id=None,
        correction_reason: str = "",
        correction_evidence_ref: str = "",
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrPersonnelDecision:
        """Append one immutable effective decision and durable outbox event."""
        decision_no = (decision_no or "").strip()
        title = (title or "").strip()
        if not decision_no:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_NO_REQUIRED", "decision_no is required"
            )
        if not title:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_TITLE_REQUIRED", "title is required"
            )
        if not content_snapshot:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_CONTENT_REQUIRED",
                "content_snapshot cannot be empty",
            )
        if decided_at is None:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_DATE_REQUIRED", "decided_at is required"
            )
        valid_types = {value for value, _label in HrPersonnelDecision.DecisionType.choices}
        if decision_type not in valid_types:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_TYPE_INVALID", "unsupported decision_type"
            )
        self._validate_effective_range(effective_from, effective_to)
        staff = self._staff(staff_id)

        correction_reason = (correction_reason or "").strip()
        correction_evidence_ref = (correction_evidence_ref or "").strip()
        expected_supersedes = None
        if decision_action == HrPersonnelDecision.DecisionAction.ISSUE:
            if supersedes_decision_id or correction_reason or correction_evidence_ref:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_SUPERSEDES_INVALID",
                    "ISSUE cannot contain correction lineage",
                )
        elif decision_action in (
            HrPersonnelDecision.DecisionAction.CORRECT,
            HrPersonnelDecision.DecisionAction.REVOKE,
        ):
            if not supersedes_decision_id:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_SUPERSEDES_REQUIRED",
                    "CORRECT/REVOKE must supersede an existing decision",
                )
            if not correction_reason or not correction_evidence_ref:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_CORRECTION_EVIDENCE_REQUIRED",
                    "CORRECT/REVOKE require reason and evidence reference",
                )
            prior = self._locked_decision(supersedes_decision_id)
            if prior.staff_id != staff.id:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_STAFF_MISMATCH",
                    "superseded decision belongs to another staff member",
                )
            if prior.decision_type != decision_type:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_TYPE_MISMATCH",
                    "successor must preserve the decision type",
                )
            successor = HrPersonnelDecision.objects.filter(
                tenant_id=self.tenant_id,
                supersedes_decision_id=prior.id,
            ).first()
            if successor is not None and successor.decision_no != decision_no:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_ALREADY_SUPERSEDED",
                    "the decision already has a successor",
                )
            expected_supersedes = prior.id
        else:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_ACTION_INVALID",
                "unsupported decision_action",
            )

        existing = (
            HrPersonnelDecision.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, decision_no=decision_no)
            .first()
        )
        expected = (
            str(staff.id),
            decision_type,
            decision_action,
            title,
            basis_text or "",
            content_snapshot,
            decided_at,
            effective_from,
            effective_to,
            str(expected_supersedes or ""),
            correction_reason,
            correction_evidence_ref,
            source_business_type or "",
            source_business_id or "",
        )
        if existing is not None:
            if self._decision_identity(existing) != expected:
                raise PersonnelAuthorityError(
                    "PERSONNEL_DECISION_IDEMPOTENCY_CONFLICT",
                    "decision_no already belongs to a different immutable fact",
                )
            return existing

        try:
            decision = HrPersonnelDecision.objects.create(
                tenant_id=self.tenant_id,
                decision_no=decision_no,
                staff=staff,
                decision_type=decision_type,
                decision_action=decision_action,
                title=title,
                basis_text=basis_text or "",
                content_snapshot_json=content_snapshot,
                decided_at=decided_at,
                effective_from=effective_from,
                effective_to=effective_to,
                supersedes_decision_id=expected_supersedes,
                correction_reason=correction_reason,
                correction_evidence_ref=correction_evidence_ref,
                source_business_type=source_business_type or "",
                source_business_id=source_business_id or "",
                correlation_id=self.correlation_id,
                created_by=self.actor_user_id,
            )
        except IntegrityError as exc:
            raise PersonnelAuthorityError(
                "PERSONNEL_DECISION_CONFLICT",
                "decision number or supersession chain conflicts with another fact",
            ) from exc

        outbox_service.personnel_decision_effective(
            self.tenant_id,
            decision_id=decision.id,
            staff_id=staff.id,
            decision_type=decision.decision_type,
            decision_action=decision.decision_action,
            effective_from=decision.effective_from,
            event_type=EVENT_PERSONNEL_DECISION_EFFECTIVE,
            correlation_id=self.correlation_id,
        )
        return decision

    @transaction.atomic
    def correct_effective_decision(
        self,
        *,
        prior_decision_id,
        decision_no: str,
        title: str,
        content_snapshot: dict,
        decided_at: datetime,
        effective_from: date,
        correction_reason: str,
        correction_evidence_ref: str,
        effective_to: Optional[date] = None,
        basis_text: str = "",
    ) -> HrPersonnelDecision:
        """Append an idempotent correction to the current chain tip."""
        prior = self._locked_decision(prior_decision_id)
        return self.create_effective_decision(
            decision_no=decision_no,
            staff_id=prior.staff_id,
            decision_type=prior.decision_type,
            decision_action=HrPersonnelDecision.DecisionAction.CORRECT,
            title=title,
            basis_text=basis_text,
            content_snapshot=content_snapshot,
            decided_at=decided_at,
            effective_from=effective_from,
            effective_to=effective_to,
            supersedes_decision_id=prior.id,
            correction_reason=correction_reason,
            correction_evidence_ref=correction_evidence_ref,
            source_business_type="HR03_PERSONNEL_DECISION_CORRECTION",
            source_business_id=str(prior.id),
        )

    @transaction.atomic
    def revoke_effective_decision(
        self,
        *,
        prior_decision_id,
        decision_no: str,
        decided_at: datetime,
        effective_from: date,
        correction_reason: str,
        correction_evidence_ref: str,
        title: str = "",
    ) -> HrPersonnelDecision:
        """Append an idempotent revocation; the prior row remains untouched."""
        prior = self._locked_decision(prior_decision_id)
        return self.create_effective_decision(
            decision_no=decision_no,
            staff_id=prior.staff_id,
            decision_type=prior.decision_type,
            decision_action=HrPersonnelDecision.DecisionAction.REVOKE,
            title=title or f"撤销：{prior.title}",
            basis_text=correction_reason,
            content_snapshot={
                "revokedDecisionId": str(prior.id),
                "priorContentHash": prior.content_hash,
            },
            decided_at=decided_at,
            effective_from=effective_from,
            supersedes_decision_id=prior.id,
            correction_reason=correction_reason,
            correction_evidence_ref=correction_evidence_ref,
            source_business_type="HR03_PERSONNEL_DECISION_REVOCATION",
            source_business_id=str(prior.id),
        )

    def effective_decisions(self, *, staff_id=None, as_of: Optional[date] = None):
        """Return only current, non-revoked Authority chain tips in the tenant."""
        queryset = HrPersonnelDecision.objects.filter(tenant_id=self.tenant_id)
        queryset = (
            queryset.effective_as_of(as_of)
            if as_of is not None
            else queryset.effective()
        )
        if staff_id is not None:
            self._staff(staff_id)
            queryset = queryset.filter(staff_id=staff_id)
        return queryset.order_by("staff_id", "decision_type", "effective_from", "id")

    @staticmethod
    def _case_identity(case: HrRewardDisciplinaryCase):
        return (
            str(case.staff_id),
            case.kind,
            case.category_code,
            case.level_code,
            case.title,
            case.reason_text,
            case.occurred_on,
            case.source_business_type,
            case.source_business_id,
        )

    @transaction.atomic
    def create_reward_disciplinary_case(
        self,
        *,
        case_no: str,
        staff_id,
        kind: str,
        category_code: str,
        title: str,
        level_code: str = "",
        reason_text: str = "",
        occurred_on: Optional[date] = None,
        source_business_type: str = "",
        source_business_id: str = "",
    ) -> HrRewardDisciplinaryCase:
        case_no = (case_no or "").strip()
        category_code = (category_code or "").strip()
        title = (title or "").strip()
        if not case_no or not category_code or not title:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_REQUIRED",
                "case_no, category_code and title are required",
            )
        if kind not in {
            HrRewardDisciplinaryCase.Kind.REWARD,
            HrRewardDisciplinaryCase.Kind.DISCIPLINE,
        }:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_KIND_INVALID", "kind must be REWARD or DISCIPLINE"
            )
        staff = self._staff(staff_id)
        existing = (
            HrRewardDisciplinaryCase.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, case_no=case_no)
            .first()
        )
        expected = (
            str(staff.id),
            kind,
            category_code,
            level_code or "",
            title,
            reason_text or "",
            occurred_on,
            source_business_type or "",
            source_business_id or "",
        )
        if existing is not None:
            if self._case_identity(existing) != expected:
                raise PersonnelAuthorityError(
                    "REWARD_DISCIPLINARY_IDEMPOTENCY_CONFLICT",
                    "case_no already belongs to a different case payload",
                )
            return existing

        return HrRewardDisciplinaryCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=case_no,
            staff=staff,
            kind=kind,
            category_code=category_code,
            level_code=level_code or "",
            title=title,
            reason_text=reason_text or "",
            occurred_on=occurred_on,
            status=HrRewardDisciplinaryCase.Status.DRAFT,
            source_business_type=source_business_type or "",
            source_business_id=source_business_id or "",
            correlation_id=self.correlation_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    def _locked_case(self, case_id) -> HrRewardDisciplinaryCase:
        case = (
            HrRewardDisciplinaryCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_NOT_FOUND",
                "reward/disciplinary case not found inside tenant",
            )
        return case

    @transaction.atomic
    def submit_reward_disciplinary_case(self, case_id):
        case = self._locked_case(case_id)
        if case.status not in {
            HrRewardDisciplinaryCase.Status.DRAFT,
            HrRewardDisciplinaryCase.Status.RETURNED,
        }:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_STATE_INVALID",
                "only DRAFT/RETURNED cases may be submitted",
            )
        case.status = HrRewardDisciplinaryCase.Status.SUBMITTED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return case

    @transaction.atomic
    def return_reward_disciplinary_case(self, case_id):
        case = self._locked_case(case_id)
        if case.status != HrRewardDisciplinaryCase.Status.SUBMITTED:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_STATE_INVALID",
                "only SUBMITTED cases may be returned",
            )
        case.status = HrRewardDisciplinaryCase.Status.RETURNED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return case

    @transaction.atomic
    def approve_reward_disciplinary_case(self, case_id):
        case = self._locked_case(case_id)
        if case.status != HrRewardDisciplinaryCase.Status.SUBMITTED:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_STATE_INVALID",
                "only SUBMITTED cases may be approved",
            )
        case.status = HrRewardDisciplinaryCase.Status.APPROVED
        case.updated_by = self.actor_user_id
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return case

    @transaction.atomic
    def reject_reward_disciplinary_case(self, case_id):
        case = self._locked_case(case_id)
        if case.status != HrRewardDisciplinaryCase.Status.SUBMITTED:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_STATE_INVALID",
                "only SUBMITTED cases may be rejected",
            )
        case.status = HrRewardDisciplinaryCase.Status.REJECTED
        case.updated_by = self.actor_user_id
        case._allow_terminal_transition = True
        case.save(update_fields=["status", "updated_by", "updated_at"])
        return case

    @transaction.atomic
    def make_reward_disciplinary_effective(
        self,
        *,
        case_id,
        decision_no: str,
        decided_at: datetime,
        effective_from: date,
        effective_to: Optional[date] = None,
        final_snapshot: Optional[dict] = None,
    ) -> HrRewardDisciplinaryCase:
        case = self._locked_case(case_id)
        if case.status == HrRewardDisciplinaryCase.Status.EFFECTIVE:
            if case.decision_id is None:
                raise PersonnelAuthorityError(
                    "REWARD_DISCIPLINARY_FACT_BROKEN",
                    "effective case has no personnel decision",
                )
            if case.decision.decision_no != decision_no:
                raise PersonnelAuthorityError(
                    "REWARD_DISCIPLINARY_IDEMPOTENCY_CONFLICT",
                    "effective case already belongs to another decision",
                )
            return case
        if case.status != HrRewardDisciplinaryCase.Status.APPROVED:
            raise PersonnelAuthorityError(
                "REWARD_DISCIPLINARY_STATE_INVALID",
                "only APPROVED cases may become effective",
            )

        frozen = {
            "caseNo": case.case_no,
            "kind": case.kind,
            "categoryCode": case.category_code,
            "levelCode": case.level_code,
            "title": case.title,
            "reasonText": case.reason_text,
            "occurredOn": case.occurred_on.isoformat() if case.occurred_on else None,
            "final": final_snapshot or {},
        }
        decision = self.create_effective_decision(
            decision_no=decision_no,
            staff_id=case.staff_id,
            decision_type=(
                HrPersonnelDecision.DecisionType.REWARD
                if case.kind == HrRewardDisciplinaryCase.Kind.REWARD
                else HrPersonnelDecision.DecisionType.DISCIPLINE
            ),
            decision_action=HrPersonnelDecision.DecisionAction.ISSUE,
            title=case.title,
            basis_text=case.reason_text,
            content_snapshot=frozen,
            decided_at=decided_at,
            effective_from=effective_from,
            effective_to=effective_to,
            source_business_type=case.source_business_type or "HR03_REWARD_DISCIPLINARY",
            source_business_id=case.source_business_id or str(case.id),
        )

        case.decision = decision
        case.final_snapshot_json = frozen
        case.status = HrRewardDisciplinaryCase.Status.EFFECTIVE
        case.updated_by = self.actor_user_id
        case._allow_terminal_transition = True
        case.save(
            update_fields=[
                "decision",
                "final_snapshot_json",
                "status",
                "updated_by",
                "updated_at",
            ]
        )
        outbox_service.reward_disciplinary_effective(
            self.tenant_id,
            case_id=case.id,
            decision_id=decision.id,
            staff_id=case.staff_id,
            kind=case.kind,
            effective_from=decision.effective_from,
            event_type=EVENT_REWARD_DISCIPLINARY_EFFECTIVE,
            correlation_id=self.correlation_id,
        )
        return case
