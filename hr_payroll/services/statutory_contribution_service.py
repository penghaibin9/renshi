"""HR15 statutory contribution rules and facts on the canonical payroll chain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import (
    EVENT_STATUTORY_CONTRIBUTION_CALCULATED,
    EVENT_STATUTORY_CONTRIBUTION_REVIEWED,
    EVENT_STATUTORY_CONTRIBUTION_SEALED,
    EVENT_STATUTORY_RULE_PUBLISHED,
)
from hr_payroll.statutory_models import (
    StatutoryContributionFact,
    StatutoryContributionRuleVersion,
)

MONEY = Decimal("0.01")


class StatutoryContributionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def evidence_hash(payload) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _decimal(value, code: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise StatutoryContributionError(code, "value must be a finite decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StatutoryContributionError(code, "value must be a finite decimal") from exc
    if not parsed.is_finite():
        raise StatutoryContributionError(code, "value must be a finite decimal")
    return parsed


@dataclass(frozen=True)
class CalculatedContribution:
    rule: StatutoryContributionRuleVersion
    requested_base: Decimal
    contribution_base: Decimal
    employee_amount: Decimal
    employer_amount: Decimal


class StatutoryContributionRuleService:
    def __init__(self, tenant_id: int, actor_user_id: int | None = None, correlation_id=""):
        if not tenant_id:
            raise StatutoryContributionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    @transaction.atomic
    def create_draft(
        self,
        *,
        rule_code,
        version_no,
        contribution_group,
        contribution_code,
        name,
        jurisdiction_code,
        base_variable_key,
        base_floor,
        base_ceiling,
        employee_rate,
        employer_rate,
        employee_item_code,
        employer_item_code,
        effective_from,
        policy_evidence,
        effective_to=None,
    ) -> StatutoryContributionRuleVersion:
        text_values = {
            "rule_code": rule_code,
            "contribution_code": contribution_code,
            "name": name,
            "jurisdiction_code": jurisdiction_code,
            "base_variable_key": base_variable_key,
            "employee_item_code": employee_item_code,
            "employer_item_code": employer_item_code,
        }
        normalized = {key: str(value or "").strip() for key, value in text_values.items()}
        if not all(normalized.values()):
            raise StatutoryContributionError(
                "STATUTORY_RULE_FIELDS_REQUIRED", "all statutory rule identity fields are required"
            )
        if contribution_group not in StatutoryContributionRuleVersion.Group.values:
            raise StatutoryContributionError(
                "STATUTORY_RULE_GROUP_INVALID", "unsupported contribution group"
            )
        try:
            version_no = int(version_no)
        except (TypeError, ValueError) as exc:
            raise StatutoryContributionError(
                "STATUTORY_RULE_VERSION_INVALID", "version_no must be a positive integer"
            ) from exc
        if version_no < 1:
            raise StatutoryContributionError(
                "STATUTORY_RULE_VERSION_INVALID", "version_no must be a positive integer"
            )
        floor = _decimal(base_floor, "STATUTORY_BASE_RANGE_INVALID")
        ceiling = _decimal(base_ceiling, "STATUTORY_BASE_RANGE_INVALID")
        employee = _decimal(employee_rate, "STATUTORY_RATE_INVALID")
        employer = _decimal(employer_rate, "STATUTORY_RATE_INVALID")
        if floor < 0 or ceiling < floor:
            raise StatutoryContributionError(
                "STATUTORY_BASE_RANGE_INVALID", "base ceiling must be at least the non-negative floor"
            )
        if employee < 0 or employee > 1 or employer < 0 or employer > 1:
            raise StatutoryContributionError(
                "STATUTORY_RATE_INVALID", "contribution rates must be between zero and one"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise StatutoryContributionError(
                "STATUTORY_EFFECTIVE_RANGE_INVALID", "effective_to must follow effective_from"
            )
        if not isinstance(policy_evidence, dict) or not policy_evidence.get("documentNo"):
            raise StatutoryContributionError(
                "STATUTORY_POLICY_EVIDENCE_REQUIRED", "policy evidence requires documentNo"
            )
        existing = StatutoryContributionRuleVersion.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            rule_code=normalized["rule_code"],
            version_no=version_no,
        ).first()
        if existing:
            expected = {
                "contribution_group": contribution_group,
                "contribution_code": normalized["contribution_code"],
                "name": normalized["name"],
                "jurisdiction_code": normalized["jurisdiction_code"],
                "base_variable_key": normalized["base_variable_key"],
                "base_floor": floor,
                "base_ceiling": ceiling,
                "employee_rate": employee,
                "employer_rate": employer,
                "employee_item_code": normalized["employee_item_code"],
                "employer_item_code": normalized["employer_item_code"],
                "effective_from": effective_from,
                "effective_to": effective_to,
                "policy_evidence_json": policy_evidence,
            }
            if any(getattr(existing, field) != value for field, value in expected.items()):
                raise StatutoryContributionError(
                    "STATUTORY_RULE_IDEMPOTENCY_CONFLICT",
                    "rule_code and version_no already belong to different content",
                )
            return existing
        return StatutoryContributionRuleVersion.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            rule_code=normalized["rule_code"],
            version_no=version_no,
            contribution_group=contribution_group,
            contribution_code=normalized["contribution_code"],
            name=normalized["name"],
            jurisdiction_code=normalized["jurisdiction_code"],
            base_variable_key=normalized["base_variable_key"],
            base_floor=floor,
            base_ceiling=ceiling,
            employee_rate=employee,
            employer_rate=employer,
            employee_item_code=normalized["employee_item_code"],
            employer_item_code=normalized["employer_item_code"],
            effective_from=effective_from,
            effective_to=effective_to,
            policy_evidence_json=policy_evidence,
        )

    @transaction.atomic
    def publish(self, rule_id) -> StatutoryContributionRuleVersion:
        rule = StatutoryContributionRuleVersion.objects.select_for_update().filter(
            id=rule_id, tenant_id=self.tenant_id
        ).first()
        if rule is None:
            raise StatutoryContributionError("STATUTORY_RULE_NOT_FOUND", "rule not found")
        if rule.status == rule.Status.PUBLISHED:
            return rule
        if rule.status != rule.Status.DRAFT:
            raise StatutoryContributionError(
                "STATUTORY_RULE_INVALID_STATE", "only a draft rule can be published"
            )
        overlaps = StatutoryContributionRuleVersion.objects.select_for_update().filter(
            tenant_id=self.tenant_id,
            contribution_code=rule.contribution_code,
            status=rule.Status.PUBLISHED,
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=rule.effective_from)
        )
        if rule.effective_to is not None:
            overlaps = overlaps.filter(effective_from__lt=rule.effective_to)
        if overlaps.exists():
            raise StatutoryContributionError(
                "STATUTORY_RULE_EFFECTIVE_OVERLAP",
                "another published version overlaps this contribution period",
            )
        payload = {
            "ruleCode": rule.rule_code,
            "versionNo": rule.version_no,
            "group": rule.contribution_group,
            "code": rule.contribution_code,
            "jurisdiction": rule.jurisdiction_code,
            "baseVariable": rule.base_variable_key,
            "baseFloor": rule.base_floor,
            "baseCeiling": rule.base_ceiling,
            "employeeRate": rule.employee_rate,
            "employerRate": rule.employer_rate,
            "employeeItemCode": rule.employee_item_code,
            "employerItemCode": rule.employer_item_code,
            "effectiveFrom": rule.effective_from,
            "effectiveTo": rule.effective_to,
            "policyEvidence": rule.policy_evidence_json,
        }
        rule.content_hash = evidence_hash(payload)
        rule.status = rule.Status.PUBLISHED
        rule.published_at = timezone.now()
        rule.updated_by = self.actor_user_id
        rule.save(
            update_fields=["content_hash", "status", "published_at", "updated_by", "updated_at"]
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_STATUTORY_RULE_PUBLISHED,
            payload={
                "ruleId": str(rule.id),
                "ruleCode": rule.rule_code,
                "versionNo": rule.version_no,
                "contentHash": rule.content_hash,
            },
            correlation_id=self.correlation_id,
        )
        return rule


class StatutoryContributionService:
    def __init__(self, tenant_id: int, actor_user_id: int | None = None, correlation_id=""):
        if not tenant_id:
            raise StatutoryContributionError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    def effective_rules(self, period) -> list[StatutoryContributionRuleVersion]:
        rules = list(
            StatutoryContributionRuleVersion.objects.filter(
                tenant_id=self.tenant_id,
                status=StatutoryContributionRuleVersion.Status.PUBLISHED,
                effective_from__lte=period.end_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=period.start_date))
            .order_by("contribution_group", "contribution_code", "version_no")
        )
        seen = set()
        for rule in rules:
            if rule.contribution_code in seen:
                raise StatutoryContributionError(
                    "STATUTORY_RULE_SET_OVERLAP",
                    f"multiple effective versions found for {rule.contribution_code}",
                )
            seen.add(rule.contribution_code)
        return rules

    @staticmethod
    def calculate(rule, variables) -> CalculatedContribution:
        if rule.base_variable_key not in variables:
            raise StatutoryContributionError(
                "STATUTORY_BASE_INPUT_MISSING",
                f"input value {rule.base_variable_key} is required for {rule.contribution_code}",
            )
        requested = _decimal(variables[rule.base_variable_key], "STATUTORY_BASE_INPUT_INVALID")
        if requested < 0:
            raise StatutoryContributionError(
                "STATUTORY_BASE_INPUT_INVALID", "contribution base cannot be negative"
            )
        base = min(max(requested, rule.base_floor), rule.base_ceiling)
        employee = (base * rule.employee_rate).quantize(MONEY, rounding=ROUND_HALF_UP)
        employer = (base * rule.employer_rate).quantize(MONEY, rounding=ROUND_HALF_UP)
        return CalculatedContribution(rule, requested, base, employee, employer)

    def create_fact(
        self,
        *,
        calculated: CalculatedContribution,
        period,
        result,
        batch,
        snapshot,
    ) -> StatutoryContributionFact:
        rule = calculated.rule
        payload = {
            "periodId": str(period.id),
            "resultId": str(result.id),
            "batchId": str(batch.id),
            "staffId": str(result.staff_id),
            "ruleId": str(rule.id),
            "ruleContentHash": rule.content_hash,
            "inputSnapshotId": str(snapshot.id),
            "inputContentHash": snapshot.content_hash,
            "requestedBase": calculated.requested_base,
            "contributionBase": calculated.contribution_base,
            "employeeRate": rule.employee_rate,
            "employerRate": rule.employer_rate,
            "employeeAmount": calculated.employee_amount,
            "employerAmount": calculated.employer_amount,
        }
        digest = evidence_hash(payload)
        existing = StatutoryContributionFact.objects.filter(
            tenant_id=self.tenant_id,
            payroll_result_id=result.id,
            rule_version_id=rule.id,
        ).first()
        if existing:
            if existing.evidence_hash != digest:
                raise StatutoryContributionError(
                    "STATUTORY_CALCULATION_IDEMPOTENCY_CONFLICT",
                    "existing contribution fact has different evidence",
                )
            return existing
        fact = StatutoryContributionFact.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            payroll_period_id=period.id,
            payroll_result_id=result.id,
            calculation_batch_id=batch.id,
            staff_id=result.staff_id,
            rule_version_id=rule.id,
            contribution_group=rule.contribution_group,
            contribution_code=rule.contribution_code,
            requested_base=calculated.requested_base,
            contribution_base=calculated.contribution_base,
            employee_rate=rule.employee_rate,
            employer_rate=rule.employer_rate,
            employee_amount=calculated.employee_amount,
            employer_amount=calculated.employer_amount,
            employee_item_code=rule.employee_item_code,
            employer_item_code=rule.employer_item_code,
            input_snapshot_id=snapshot.id,
            input_content_hash=snapshot.content_hash,
            rule_content_hash=rule.content_hash,
            evidence_hash=digest,
        )
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_STATUTORY_CONTRIBUTION_CALCULATED,
            payload={
                "factId": str(fact.id),
                "resultId": str(result.id),
                "staffId": str(result.staff_id),
                "contributionCode": fact.contribution_code,
                "evidenceHash": fact.evidence_hash,
            },
            correlation_id=self.correlation_id,
        )
        return fact

    def review_for_result(self, *, result_id, review) -> tuple[str, ...]:
        if review.decision != review.Decision.APPROVED:
            return ()
        facts = list(
            StatutoryContributionFact.objects.select_for_update().filter(
                tenant_id=self.tenant_id, payroll_result_id=result_id
            )
        )
        reviewed = []
        for fact in facts:
            digest = evidence_hash(
                {
                    "factEvidenceHash": fact.evidence_hash,
                    "reviewId": str(review.id),
                    "decision": review.decision,
                    "reviewedBy": review.reviewed_by,
                    "reviewedAt": review.reviewed_at,
                    "note": review.note,
                }
            )
            if fact.status in {fact.Status.REVIEWED, fact.Status.SEALED}:
                if fact.review_evidence_hash != digest:
                    raise StatutoryContributionError(
                        "STATUTORY_REVIEW_IDEMPOTENCY_CONFLICT",
                        "contribution fact already has different review evidence",
                    )
                reviewed.append(str(fact.id))
                continue
            fact.status = fact.Status.REVIEWED
            fact.review_evidence_hash = digest
            fact.reviewed_by = review.reviewed_by
            fact.reviewed_at = review.reviewed_at
            fact.updated_by = review.reviewed_by
            fact.save(
                update_fields=[
                    "status",
                    "review_evidence_hash",
                    "reviewed_by",
                    "reviewed_at",
                    "updated_by",
                    "updated_at",
                ]
            )
            reviewed.append(str(fact.id))
        if reviewed:
            emit_registered_event(
                tenant_id=self.tenant_id,
                event_name=EVENT_STATUTORY_CONTRIBUTION_REVIEWED,
                payload={"resultId": str(result_id), "factIds": reviewed, "reviewId": str(review.id)},
                correlation_id=self.correlation_id,
            )
        return tuple(reviewed)

    def seal_period(self, *, period_id, sealed_at=None) -> tuple[str, ...]:
        from hr_payroll.calculation_models import PayrollCalculationLine, PayrollReviewFact

        facts = list(
            StatutoryContributionFact.objects.select_for_update().filter(
                tenant_id=self.tenant_id, payroll_period_id=period_id
            )
        )
        invalid = [str(fact.id) for fact in facts if fact.status != fact.Status.REVIEWED]
        if invalid:
            raise StatutoryContributionError(
                "STATUTORY_REVIEW_INCOMPLETE",
                "all statutory contribution facts must be reviewed before payroll finalization",
            )
        rules = {
            rule.id: rule
            for rule in StatutoryContributionRuleVersion.objects.filter(
                tenant_id=self.tenant_id,
                id__in=[fact.rule_version_id for fact in facts],
            )
        }
        for fact in facts:
            rule = rules.get(fact.rule_version_id)
            if rule is None or rule.content_hash != fact.rule_content_hash:
                raise StatutoryContributionError(
                    "STATUTORY_RULE_EVIDENCE_INVALID",
                    "contribution fact no longer matches its immutable rule evidence",
                )
            calculated = self.calculate(rule, {rule.base_variable_key: fact.requested_base})
            expected_evidence_hash = evidence_hash(
                {
                    "periodId": str(fact.payroll_period_id),
                    "resultId": str(fact.payroll_result_id),
                    "batchId": str(fact.calculation_batch_id),
                    "staffId": str(fact.staff_id),
                    "ruleId": str(rule.id),
                    "ruleContentHash": rule.content_hash,
                    "inputSnapshotId": str(fact.input_snapshot_id),
                    "inputContentHash": fact.input_content_hash,
                    "requestedBase": calculated.requested_base,
                    "contributionBase": calculated.contribution_base,
                    "employeeRate": rule.employee_rate,
                    "employerRate": rule.employer_rate,
                    "employeeAmount": calculated.employee_amount,
                    "employerAmount": calculated.employer_amount,
                }
            )
            review = PayrollReviewFact.objects.filter(
                tenant_id=self.tenant_id,
                payroll_result_id=fact.payroll_result_id,
                decision=PayrollReviewFact.Decision.APPROVED,
            ).first()
            expected_review_hash = ""
            if review is not None:
                expected_review_hash = evidence_hash(
                    {
                        "factEvidenceHash": fact.evidence_hash,
                        "reviewId": str(review.id),
                        "decision": review.decision,
                        "reviewedBy": review.reviewed_by,
                        "reviewedAt": review.reviewed_at,
                        "note": review.note,
                    }
                )
            if (
                fact.contribution_group != rule.contribution_group
                or fact.contribution_code != rule.contribution_code
                or fact.contribution_base != calculated.contribution_base
                or fact.employee_amount != calculated.employee_amount
                or fact.employer_amount != calculated.employer_amount
                or fact.evidence_hash != expected_evidence_hash
                or fact.review_evidence_hash != expected_review_hash
            ):
                raise StatutoryContributionError(
                    "STATUTORY_CALCULATION_EVIDENCE_INVALID",
                    "contribution amounts or review evidence do not reconcile",
                )
            expected_lines = (
                (fact.employee_item_code, fact.employee_amount, "DEDUCTION"),
                (fact.employer_item_code, fact.employer_amount, "EMPLOYER"),
            )
            for item_code, amount, item_type in expected_lines:
                line = PayrollCalculationLine.objects.filter(
                    tenant_id=self.tenant_id,
                    calculation_batch_id=fact.calculation_batch_id,
                    payroll_result_id=fact.payroll_result_id,
                    staff_id=fact.staff_id,
                    item_code=item_code,
                    rule_version_id=fact.rule_version_id,
                ).first()
                if line is None or line.amount != amount or line.item_type != item_type:
                    raise StatutoryContributionError(
                        "STATUTORY_PAYROLL_LINE_MISMATCH",
                        "statutory contribution does not reconcile with canonical payroll lines",
                    )
        sealed_at = sealed_at or timezone.now()
        ids = []
        for fact in facts:
            fact.status = fact.Status.SEALED
            fact.sealed_at = sealed_at
            fact.save(update_fields=["status", "sealed_at", "updated_at"])
            ids.append(str(fact.id))
        if ids:
            emit_registered_event(
                tenant_id=self.tenant_id,
                event_name=EVENT_STATUTORY_CONTRIBUTION_SEALED,
                payload={"periodId": str(period_id), "factIds": ids, "sealedAt": sealed_at.isoformat()},
                correlation_id=self.correlation_id,
            )
        return tuple(ids)
