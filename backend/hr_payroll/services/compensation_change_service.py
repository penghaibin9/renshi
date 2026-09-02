"""Approval and payroll-input boundary for effective-dated compensation changes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import (
    EVENT_COMPENSATION_CHANGE_APPROVED,
    EVENT_COMPENSATION_CHANGE_REJECTED,
    EVENT_COMPENSATION_CHANGE_SUBMITTED,
)
from hr_payroll.compensation_models import CompensationChangeCase
from hr_staff.models import HrStaffMaster


class CompensationChangeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _hash(payload) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _money(value) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CompensationChangeError(
            "COMPENSATION_CHANGE_AMOUNT_INVALID", "amount must be a decimal value"
        )
    try:
        result = Decimal(str(value)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CompensationChangeError(
            "COMPENSATION_CHANGE_AMOUNT_INVALID", "amount must be a decimal value"
        ) from exc
    if not result.is_finite():
        raise CompensationChangeError(
            "COMPENSATION_CHANGE_AMOUNT_INVALID", "amount must be finite"
        )
    return result


def _payload(case: CompensationChangeCase) -> dict:
    return {
        "caseNo": case.case_no,
        "staffId": str(case.staff_id),
        "changeType": case.change_type,
        "payrollVariableKey": case.payroll_variable_key,
        "itemName": case.item_name,
        "amountMode": case.amount_mode,
        "amount": str(case.amount),
        "currencyCode": case.currency_code,
        "prorationMode": case.proration_mode,
        "effectiveFrom": case.effective_from,
        "effectiveTo": case.effective_to,
        "reviewDate": case.review_date,
        "reasonCode": case.reason_code,
        "note": case.note,
        "sourceDomain": case.source_domain,
        "sourceRef": case.source_ref,
        "sourceVersion": case.source_version,
        "sourceSnapshot": case.source_snapshot_json,
        "evidenceRefs": case.evidence_refs_json,
        "supersedesCaseId": (
            str(case.supersedes_case_id) if case.supersedes_case_id else None
        ),
    }


class CompensationChangeService:
    def __init__(self, tenant_id: int, *, actor_user_id=None, correlation_id=""):
        if not tenant_id:
            raise CompensationChangeError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    def _case(self, case_id, *, lock=False) -> CompensationChangeCase:
        qs = (
            CompensationChangeCase.objects.select_for_update()
            if lock
            else CompensationChangeCase.objects
        )
        try:
            case = qs.filter(id=case_id, tenant_id=self.tenant_id).first()
        except (TypeError, ValueError, ValidationError) as exc:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_NOT_FOUND", "compensation change not found"
            ) from exc
        if case is None:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_NOT_FOUND", "compensation change not found"
            )
        return case

    def _staff_exists(self, staff_id) -> bool:
        try:
            return HrStaffMaster.objects.filter(
                id=staff_id, tenant_id=self.tenant_id
            ).exists()
        except (TypeError, ValueError, ValidationError):
            return False

    @transaction.atomic
    def create_draft(
        self,
        *,
        case_no,
        staff_id,
        change_type,
        payroll_variable_key,
        item_name,
        amount_mode,
        amount,
        effective_from,
        reason_code,
        currency_code="CNY",
        proration_mode="NONE",
        effective_to=None,
        review_date=None,
        note="",
        source_domain="",
        source_ref="",
        source_version="",
        source_snapshot=None,
        evidence_refs=None,
        supersedes_case_id=None,
    ) -> CompensationChangeCase:
        case_no = str(case_no or "").strip().upper()
        payroll_variable_key = str(payroll_variable_key or "").strip()
        item_name = str(item_name or "").strip()
        reason_code = str(reason_code or "").strip().upper()
        change_type = str(change_type or "").strip().upper()
        amount_mode = str(amount_mode or "SET").strip().upper()
        currency_code = str(currency_code or "CNY").strip().upper()
        proration_mode = str(proration_mode or "NONE").strip().upper()
        amount = _money(amount)
        source_snapshot = source_snapshot or {}
        evidence_refs = evidence_refs or []
        if not all((case_no, payroll_variable_key, item_name, reason_code)):
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_FIELDS_REQUIRED",
                "case number, payroll variable, item name and reason are required",
            )
        if change_type not in CompensationChangeCase.ChangeType.values:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_TYPE_INVALID", "change type is invalid"
            )
        if amount_mode not in CompensationChangeCase.AmountMode.values:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_AMOUNT_MODE_INVALID", "amount mode is invalid"
            )
        if proration_mode not in CompensationChangeCase.ProrationMode.values:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_PRORATION_INVALID", "proration mode is invalid"
            )
        if amount_mode == CompensationChangeCase.AmountMode.SET and amount < 0:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_AMOUNT_INVALID", "set amount cannot be negative"
            )
        if len(currency_code) != 3:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_CURRENCY_INVALID", "currency code is invalid"
            )
        if not isinstance(effective_from, date):
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_DATE_INVALID", "effective date is required"
            )
        if effective_to is not None and effective_to < effective_from:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_DATE_INVALID", "effective date range is invalid"
            )
        if review_date is not None and review_date < effective_from:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_DATE_INVALID", "review date precedes effective date"
            )
        if not isinstance(source_snapshot, dict) or not isinstance(evidence_refs, list):
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_EVIDENCE_INVALID",
                "source snapshot and evidence references are invalid",
            )
        try:
            json.dumps(source_snapshot, ensure_ascii=False)
            json.dumps(evidence_refs, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_EVIDENCE_INVALID",
                "source snapshot or evidence references are not serializable",
            ) from exc
        if not self._staff_exists(staff_id):
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_STAFF_NOT_FOUND",
                "staff not found inside tenant",
            )
        prior = None
        if supersedes_case_id:
            prior = self._case(supersedes_case_id, lock=True)
            if (
                str(prior.staff_id) != str(staff_id)
                or prior.payroll_variable_key != payroll_variable_key
                or prior.status != CompensationChangeCase.Status.APPROVED
            ):
                raise CompensationChangeError(
                    "COMPENSATION_CHANGE_SUPERSEDES_INVALID",
                    "superseded case is not an approved matching staff item",
                )
        existing = CompensationChangeCase.objects.select_for_update().filter(
            tenant_id=self.tenant_id, case_no=case_no
        ).first()
        requested = {
            "staffId": str(staff_id),
            "changeType": change_type,
            "payrollVariableKey": payroll_variable_key,
            "itemName": item_name,
            "amountMode": amount_mode,
            "amount": str(amount),
            "currencyCode": currency_code,
            "prorationMode": proration_mode,
            "effectiveFrom": effective_from,
            "effectiveTo": effective_to,
            "reviewDate": review_date,
            "reasonCode": reason_code,
            "note": str(note or "").strip(),
            "sourceDomain": str(source_domain or "").strip().upper(),
            "sourceRef": str(source_ref or "").strip(),
            "sourceVersion": str(source_version or "").strip(),
            "sourceSnapshot": source_snapshot,
            "evidenceRefs": evidence_refs,
            "supersedesCaseId": str(prior.id) if prior else None,
        }
        if existing:
            if {key: value for key, value in _payload(existing).items() if key != "caseNo"} == requested:
                return existing
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_IDEMPOTENCY_CONFLICT",
                "case number already exists with different content",
            )
        case = CompensationChangeCase(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            case_no=case_no,
            staff_id=staff_id,
            change_type=change_type,
            payroll_variable_key=payroll_variable_key,
            item_name=item_name,
            amount_mode=amount_mode,
            amount=amount,
            currency_code=currency_code,
            proration_mode=proration_mode,
            effective_from=effective_from,
            effective_to=effective_to,
            review_date=review_date,
            reason_code=reason_code,
            note=requested["note"],
            source_domain=requested["sourceDomain"],
            source_ref=requested["sourceRef"],
            source_version=requested["sourceVersion"],
            source_snapshot_json=source_snapshot,
            evidence_refs_json=evidence_refs,
            supersedes_case_id=prior.id if prior else None,
        )
        try:
            case.full_clean()
        except ValidationError as exc:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_INPUT_INVALID", "change case fields are invalid"
            ) from exc
        case.save()
        return case

    @transaction.atomic
    def submit(self, case_id) -> CompensationChangeCase:
        case = self._case(case_id, lock=True)
        if case.status == CompensationChangeCase.Status.SUBMITTED:
            return case
        if case.status != CompensationChangeCase.Status.DRAFT:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_STATE_INVALID", "only a draft may be submitted"
            )
        if case.change_type in {
            CompensationChangeCase.ChangeType.ALLOWANCE_CHANGE,
            CompensationChangeCase.ChangeType.ALLOWANCE_STOP,
        } and not case.supersedes_case_id:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_SUPERSEDES_REQUIRED",
                "allowance change or stop must supersede an approved case",
            )
        case.content_hash = _hash(_payload(case))
        case.status = CompensationChangeCase.Status.SUBMITTED
        case.submitted_by = self.actor_user_id
        case.submitted_at = timezone.now()
        case.updated_by = self.actor_user_id
        case.save(
            update_fields=(
                "content_hash",
                "status",
                "submitted_by",
                "submitted_at",
                "updated_by",
                "updated_at",
            )
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_COMPENSATION_CHANGE_SUBMITTED,
            payload={
                "caseId": str(case.id),
                "caseNo": case.case_no,
                "contentHash": case.content_hash,
            },
            correlation_id=self.correlation_id,
        )
        return case

    @transaction.atomic
    def approve(self, case_id, *, decision_note="") -> CompensationChangeCase:
        case = self._case(case_id, lock=True)
        if case.status == CompensationChangeCase.Status.APPROVED:
            return case
        if case.status != CompensationChangeCase.Status.SUBMITTED:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_STATE_INVALID", "only a submitted case may be approved"
            )
        if self.actor_user_id is None or self.actor_user_id == case.submitted_by:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_MAKER_CHECKER_REQUIRED",
                "submitter and approver must be different users",
            )
        conflicts = (
            CompensationChangeCase.objects.select_for_update()
            .filter(
                tenant_id=self.tenant_id,
                staff_id=case.staff_id,
                payroll_variable_key=case.payroll_variable_key,
                status=CompensationChangeCase.Status.APPROVED,
                effective_from__lte=case.effective_to or date.max,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=case.effective_from))
        )
        if case.supersedes_case_id:
            conflicts = conflicts.exclude(id=case.supersedes_case_id)
        superseded_ids = CompensationChangeCase.objects.filter(
            tenant_id=self.tenant_id,
            status=CompensationChangeCase.Status.APPROVED,
            supersedes_case_id__isnull=False,
        ).values_list("supersedes_case_id", flat=True)
        if conflicts.exclude(id__in=superseded_ids).exists():
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_EFFECTIVE_CONFLICT",
                "another approved change is effective for this staff item",
            )
        case.status = CompensationChangeCase.Status.APPROVED
        case.decided_by = self.actor_user_id
        case.decided_at = timezone.now()
        case.decision_note = str(decision_note or "").strip()
        case.updated_by = self.actor_user_id
        case.save(
            update_fields=(
                "status",
                "decided_by",
                "decided_at",
                "decision_note",
                "updated_by",
                "updated_at",
            )
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_COMPENSATION_CHANGE_APPROVED,
            payload={
                "caseId": str(case.id),
                "caseNo": case.case_no,
                "staffId": str(case.staff_id),
                "effectiveDate": case.effective_from.isoformat(),
                "contentHash": case.content_hash,
            },
            correlation_id=self.correlation_id,
        )
        return case

    @transaction.atomic
    def reject(self, case_id, *, decision_note) -> CompensationChangeCase:
        note = str(decision_note or "").strip()
        if not note:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_DECISION_NOTE_REQUIRED",
                "rejection reason is required",
            )
        case = self._case(case_id, lock=True)
        if case.status == CompensationChangeCase.Status.REJECTED:
            return case
        if case.status != CompensationChangeCase.Status.SUBMITTED:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_STATE_INVALID", "only a submitted case may be rejected"
            )
        if self.actor_user_id is None or self.actor_user_id == case.submitted_by:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_MAKER_CHECKER_REQUIRED",
                "submitter and approver must be different users",
            )
        case.status = CompensationChangeCase.Status.REJECTED
        case.decided_by = self.actor_user_id
        case.decided_at = timezone.now()
        case.decision_note = note
        case.updated_by = self.actor_user_id
        case.save(
            update_fields=(
                "status",
                "decided_by",
                "decided_at",
                "decision_note",
                "updated_by",
                "updated_at",
            )
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_COMPENSATION_CHANGE_REJECTED,
            payload={"caseId": str(case.id), "caseNo": case.case_no},
            correlation_id=self.correlation_id,
        )
        return case

    def effective_cases(self, *, staff_id, period_start, period_end):
        try:
            eligible = (
                CompensationChangeCase.objects.filter(
                    tenant_id=self.tenant_id,
                    staff_id=staff_id,
                    status=CompensationChangeCase.Status.APPROVED,
                    effective_from__lte=period_end,
                )
                .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=period_start))
                .order_by("effective_from", "case_no", "id")
            )
            return list(eligible)
        except DatabaseError as exc:
            raise CompensationChangeError(
                "COMPENSATION_CHANGE_PROVIDER_UNAVAILABLE",
                "compensation change ledger is unavailable",
            ) from exc

    def payroll_input_source(
        self, *, staff_id, period_id, period_start, period_end, base_variables
    ) -> dict | None:
        cases = self.effective_cases(
            staff_id=staff_id,
            period_start=period_start,
            period_end=period_end,
        )
        if not cases:
            return None
        variables = {}
        evidence = []
        period_day_count = (period_end - period_start).days + 1
        period_days = Decimal(period_day_count)
        grouped = defaultdict(list)
        for case in cases:
            grouped[case.payroll_variable_key].append(case)
            evidence.append(
                {
                    "caseId": str(case.id),
                    "caseNo": case.case_no,
                    "contentHash": case.content_hash,
                    "amountMode": case.amount_mode,
                    "prorationMode": case.proration_mode,
                    "effectiveFrom": case.effective_from.isoformat(),
                    "effectiveTo": (
                        case.effective_to.isoformat() if case.effective_to else None
                    ),
                }
            )
        for variable_key, variable_cases in grouped.items():
            try:
                base = Decimal(str(base_variables.get(variable_key, 0)))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise CompensationChangeError(
                    "COMPENSATION_CHANGE_BASE_INVALID",
                    "base payroll variable is not a decimal value",
                ) from exc
            if not base.is_finite():
                raise CompensationChangeError(
                    "COMPENSATION_CHANGE_BASE_INVALID",
                    "base payroll variable must be finite",
                )
            if len(variable_cases) == 1 and variable_cases[0].proration_mode == CompensationChangeCase.ProrationMode.NONE:
                case = variable_cases[0]
                value = (
                    case.amount
                    if case.amount_mode == CompensationChangeCase.AmountMode.SET
                    else base + case.amount
                )
            else:
                if any(
                    case.proration_mode
                    != CompensationChangeCase.ProrationMode.CALENDAR_DAYS
                    for case in variable_cases
                ):
                    raise CompensationChangeError(
                        "COMPENSATION_CHANGE_PRORATION_REQUIRED",
                        "multiple changes in one period require calendar-day proration",
                    )
                total = Decimal("0")
                for offset in range(period_day_count):
                    current_day = period_start + timedelta(days=offset)
                    active = [
                        case
                        for case in variable_cases
                        if case.effective_from <= current_day
                        and (case.effective_to is None or case.effective_to >= current_day)
                    ]
                    if not active:
                        total += base
                        continue
                    case = max(active, key=lambda item: (item.effective_from, item.case_no, item.id))
                    total += (
                        case.amount
                        if case.amount_mode == CompensationChangeCase.AmountMode.SET
                        else base + case.amount
                    )
                value = total / period_days
            variables[variable_key] = str(
                value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
        evidence_id = _hash(evidence)
        return {
            "authority": "HR15_CHANGE",
            "tenantId": self.tenant_id,
            "periodId": str(period_id),
            "staffId": str(staff_id),
            "version": "hr15.compensation-change.1",
            "evidenceId": evidence_id,
            "snapshot": {"cases": evidence},
            "variables": variables,
        }
