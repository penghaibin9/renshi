"""HR09 system precheck engine.

Evaluation order is intentionally fail-closed:
1. provider health,
2. evidence-requirement gates,
3. typed rule DSL.
Unknown/invalid DSL never becomes PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from hr_qualification.constants import (
    HardOrSoft,
    PrecheckResultType,
    ProviderStatus as PS,
    RuleType,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRule,
)
from hr_qualification.providers.base import ProviderEvidenceResult


_TRUSTED_VERIFICATION_STATUSES = {
    "VERIFIED",
    "FINALIZED",
    "SYSTEM_PROVIDER_VERIFIED",
    "TRAINING_PROVIDER_VERIFIED",
    "INTERNAL_INSTRUCTOR_VERIFIED",
    "HR_VERIFIED",
    "DOCUMENT_VERIFIED",
    "MANUAL_COMMITTEE_VERIFIED",
    "MIGRATED_VERIFIED",
}


@dataclass
class PrecheckItem:
    rule_code: str
    dimension_code: str
    level: str
    hard_or_soft: str
    result: PrecheckResultType
    evidence_count: int = 0
    detail: str = ""


@dataclass
class PrecheckResult:
    application_id: str
    overall: PrecheckResultType
    items: list[PrecheckItem] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    manual_review: int = 0
    missing: int = 0
    source_unavailable: int = 0
    rule_error: int = 0


@dataclass(frozen=True)
class _RequirementState:
    requirement: object
    qualified: tuple
    passed: bool
    missing_reason: str = ""
    rule_error: str = ""


class PrecheckService:
    @staticmethod
    def precheck(
        application: HrDoubleTeacherApplication,
        evidence_package: HrDoubleTeacherEvidencePackage,
        provider_results: dict[str, ProviderEvidenceResult] | None = None,
    ) -> PrecheckResult:
        rules = list(
            HrDoubleTeacherRule.objects.filter(
                version_id=application.batch_id.rule_pack_version_id,
                level=application.target_level,
            )
            .prefetch_related("evidence_requirements")
            .order_by("sequence")
        )
        evidence_items = list(
            HrDoubleTeacherEvidenceItem.objects.filter(package_id=evidence_package)
        )
        as_of = PrecheckService._package_as_of(evidence_package)

        items: list[PrecheckItem] = []
        passed = failed = manual = missing = src_unavailable = rule_error = 0
        for rule in rules:
            item = PrecheckService._evaluate_rule(
                rule,
                evidence_items,
                provider_results,
                as_of=as_of,
            )
            items.append(item)
            if item.result == PrecheckResultType.PASS:
                passed += 1
            elif item.result == PrecheckResultType.FAIL_HARD_RULE:
                failed += 1
            elif item.result == PrecheckResultType.MANUAL_REVIEW_REQUIRED:
                manual += 1
            elif item.result == PrecheckResultType.MISSING_EVIDENCE:
                missing += 1
            elif item.result == PrecheckResultType.SOURCE_UNAVAILABLE:
                src_unavailable += 1
            elif item.result == PrecheckResultType.RULE_ERROR:
                rule_error += 1

        overall = PrecheckResultType.PASS
        if failed > 0:
            overall = PrecheckResultType.FAIL_HARD_RULE
        elif rule_error > 0:
            overall = PrecheckResultType.RULE_ERROR
        elif src_unavailable > 0:
            overall = PrecheckResultType.SOURCE_UNAVAILABLE
        elif missing > 0:
            overall = PrecheckResultType.MISSING_EVIDENCE
        elif manual > 0:
            overall = PrecheckResultType.MANUAL_REVIEW_REQUIRED

        return PrecheckResult(
            application_id=str(application.id),
            overall=overall,
            items=items,
            passed=passed,
            failed=failed,
            manual_review=manual,
            missing=missing,
            source_unavailable=src_unavailable,
            rule_error=rule_error,
        )

    @staticmethod
    def _package_as_of(package) -> date | None:
        snapshots = package.source_snapshots_json or {}
        raw = (snapshots.get("_meta") or {}).get("asOf")
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            return None

    @staticmethod
    def _base_item(rule, result, *, evidence_count=0, detail="") -> PrecheckItem:
        return PrecheckItem(
            rule_code=rule.rule_code,
            dimension_code=rule.dimension_code,
            level=rule.level,
            hard_or_soft=rule.hard_or_soft,
            result=result,
            evidence_count=evidence_count,
            detail=detail,
        )

    @staticmethod
    def _provider_gate(rule, provider_results):
        source = str(rule.source_provider or "").strip()
        if not source:
            return None
        if provider_results is None or source not in provider_results:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.SOURCE_UNAVAILABLE,
                detail=f"Provider {source} result is missing",
            )
        status = str(provider_results[source].status)
        if status == PS.ERROR:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.RULE_ERROR,
                detail=f"Provider {source} returned ERROR",
            )
        if status in {PS.UNAVAILABLE, PS.PARTIAL, PS.STALE}:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.SOURCE_UNAVAILABLE,
                detail=f"Provider {source} is {status}",
            )
        if status not in {PS.OK, PS.NOT_APPLICABLE}:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.RULE_ERROR,
                detail=f"Provider {source} returned unknown status {status}",
            )
        return None

    @staticmethod
    def _verified(item) -> bool:
        return str(item.verification_status or "").upper() in _TRUSTED_VERIFICATION_STATUSES

    @staticmethod
    def _qualified_for_requirement(item, requirement) -> bool:
        if requirement.verification_required and not PrecheckService._verified(item):
            return False
        if requirement.document_required and not (item.document_refs or []):
            return False
        return True

    @staticmethod
    def _item_rank(item) -> Decimal | None:
        raw = (item.snapshot_json or {}).get("level_rank")
        if raw is None:
            raw = item.quantitative_value
        if raw is None:
            return None
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _requirement_states(rule, evidence_items) -> list[_RequirementState]:
        states: list[_RequirementState] = []
        for requirement in rule.evidence_requirements.all():
            related = [
                item
                for item in evidence_items
                if str(item.requirement_id_id or "") == str(requirement.id)
            ]
            qualified = tuple(
                item
                for item in related
                if PrecheckService._qualified_for_requirement(item, requirement)
            )
            missing_reason = ""
            rule_error = ""
            passed = True
            if len(qualified) < int(requirement.min_count or 0):
                passed = False
                missing_reason = (
                    f"Requirement {requirement.id} needs {requirement.min_count} qualified evidence item(s); "
                    f"got {len(qualified)}"
                )
            if passed and requirement.min_duration is not None:
                duration = sum(
                    (
                        Decimal(str(item.quantitative_value))
                        for item in qualified
                        if item.quantitative_value is not None
                    ),
                    Decimal("0"),
                )
                if duration < Decimal(requirement.min_duration):
                    passed = False
                    missing_reason = (
                        f"Requirement {requirement.id} needs duration {requirement.min_duration}; got {duration}"
                    )
            if passed and str(requirement.min_level or "").strip():
                try:
                    target_rank = Decimal(str(requirement.min_level))
                except (InvalidOperation, ValueError, TypeError):
                    passed = False
                    rule_error = (
                        f"Requirement {requirement.id} min_level must be a normalized numeric rank; "
                        "string ordering is not guessed"
                    )
                else:
                    ranks = [
                        rank
                        for rank in (PrecheckService._item_rank(item) for item in qualified)
                        if rank is not None
                    ]
                    if not ranks:
                        passed = False
                        rule_error = (
                            f"Requirement {requirement.id} has min_level but evidence has no normalized rank"
                        )
                    elif max(ranks) < target_rank:
                        passed = False
                        missing_reason = (
                            f"Requirement {requirement.id} needs level rank {target_rank}; got {max(ranks)}"
                        )
            states.append(
                _RequirementState(
                    requirement=requirement,
                    qualified=qualified,
                    passed=passed,
                    missing_reason=missing_reason,
                    rule_error=rule_error,
                )
            )
        return states

    @staticmethod
    def _expected_number(expected: dict, *keys: str) -> Decimal | None:
        for key in keys:
            if key not in expected or expected[key] is None:
                continue
            try:
                return Decimal(str(expected[key]))
            except (InvalidOperation, ValueError, TypeError):
                return None
        return None

    @staticmethod
    def _compare(actual: Decimal, expected: Decimal, operator: str) -> bool:
        operator = str(operator or ">=").upper()
        if operator == ">=":
            return actual >= expected
        if operator == "<=":
            return actual <= expected
        if operator in {"==", "="}:
            return actual == expected
        if operator == ">":
            return actual > expected
        if operator == "<":
            return actual < expected
        return False

    @staticmethod
    def _rule_failure(rule, *, evidence_count: int, detail: str):
        result = (
            PrecheckResultType.FAIL_HARD_RULE
            if rule.hard_or_soft == HardOrSoft.HARD
            else PrecheckResultType.MANUAL_REVIEW_REQUIRED
        )
        return PrecheckService._base_item(
            rule,
            result,
            evidence_count=evidence_count,
            detail=detail,
        )

    @staticmethod
    def _evaluate_rule(
        rule: HrDoubleTeacherRule,
        evidence_items: list[HrDoubleTeacherEvidenceItem],
        provider_results: dict[str, ProviderEvidenceResult] | None = None,
        *,
        as_of: date | None = None,
    ) -> PrecheckItem:
        provider_gate = PrecheckService._provider_gate(rule, provider_results)
        if provider_gate is not None:
            return provider_gate

        if rule.manual_review_required or rule.rule_type == RuleType.MANUAL_COMMITTEE:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.MANUAL_REVIEW_REQUIRED,
                detail="Manual review required by rule",
            )

        states = PrecheckService._requirement_states(rule, evidence_items)
        if not states:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.RULE_ERROR,
                detail="Non-manual rule has no evidence requirement",
            )
        rule_errors = [state.rule_error for state in states if state.rule_error]
        qualified = [item for state in states for item in state.qualified]
        if rule_errors:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.RULE_ERROR,
                evidence_count=len(qualified),
                detail="; ".join(rule_errors),
            )

        rule_type = str(rule.rule_type)
        combination_types = {RuleType.ANY_OF, RuleType.ONE_OF, RuleType.ALL_OF}
        if rule_type not in combination_types:
            missing_states = [state for state in states if not state.passed]
            if missing_states:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.MISSING_EVIDENCE,
                    evidence_count=len(qualified),
                    detail="; ".join(state.missing_reason for state in missing_states),
                )

        expected = rule.expected_value_json or {}
        if not isinstance(expected, dict):
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.RULE_ERROR,
                evidence_count=len(qualified),
                detail="expected_value_json must be an object",
            )

        if rule_type == RuleType.BOOLEAN_FACT:
            if "value" not in expected or not isinstance(expected.get("value"), bool):
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail="BOOLEAN_FACT requires boolean expected_value_json.value",
                )
            actual = bool(qualified)
            if actual != expected["value"]:
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=f"Boolean fact expected {expected['value']}, got {actual}",
                )

        elif rule_type == RuleType.COUNT:
            target = PrecheckService._expected_number(expected, "min_count", "count", "value")
            if target is None:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail="COUNT requires numeric min_count/count/value",
                )
            actual = Decimal(len(qualified))
            if not PrecheckService._compare(actual, target, rule.operator):
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=f"Count {actual} does not satisfy {rule.operator} {target}",
                )

        elif rule_type == RuleType.DURATION:
            target = PrecheckService._expected_number(expected, "min_days", "days", "value")
            if target is None:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail="DURATION requires numeric min_days/days/value",
                )
            actual = sum(
                (
                    Decimal(str(item.quantitative_value))
                    for item in qualified
                    if item.quantitative_value is not None
                ),
                Decimal("0"),
            )
            if not PrecheckService._compare(actual, target, rule.operator):
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=f"Duration {actual} does not satisfy {rule.operator} {target}",
                )

        elif rule_type in {RuleType.LEVEL_AT_LEAST, RuleType.AWARD_LEVEL}:
            target = PrecheckService._expected_number(expected, "min_rank", "rank")
            if target is None:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail=f"{rule_type} requires numeric min_rank/rank; string levels are not guessed",
                )
            ranks = [
                rank
                for rank in (PrecheckService._item_rank(item) for item in qualified)
                if rank is not None
            ]
            if not ranks:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail=f"{rule_type} evidence has no normalized numeric rank",
                )
            actual = max(ranks)
            if actual < target:
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=f"Best rank {actual} is below required rank {target}",
                )

        elif rule_type in combination_types:
            hits = [state.passed for state in states]
            if rule_type == RuleType.ANY_OF:
                passed = any(hits)
            elif rule_type == RuleType.ONE_OF:
                passed = sum(1 for hit in hits if hit) == 1
            else:
                passed = all(hits)
            if not passed:
                detail = "; ".join(
                    state.missing_reason for state in states if not state.passed
                ) or f"{rule_type} requirement combination not satisfied"
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=detail,
                )

        elif rule_type in {RuleType.ROLE_REQUIRED, RuleType.PROJECT_ROLE}:
            expected_roles = expected.get("roles")
            if expected_roles is None:
                single = expected.get("role", expected.get("value"))
                expected_roles = [single] if single else []
            if not isinstance(expected_roles, list) or not expected_roles:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail=f"{rule_type} requires role/roles",
                )
            if not any(item.role in expected_roles for item in qualified):
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=f"No evidence role is in {expected_roles}",
                )

        elif rule_type == RuleType.DATE_VALID:
            if as_of is None:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail="DATE_VALID requires package as_of metadata",
                )
            max_age = PrecheckService._expected_number(expected, "max_age_days")
            if max_age is None:
                return PrecheckService._base_item(
                    rule,
                    PrecheckResultType.RULE_ERROR,
                    evidence_count=len(qualified),
                    detail="DATE_VALID requires max_age_days",
                )
            fresh = [
                item
                for item in qualified
                if item.evidence_date is not None
                and Decimal((as_of - item.evidence_date).days) <= max_age
            ]
            if not fresh:
                return PrecheckService._rule_failure(
                    rule,
                    evidence_count=len(qualified),
                    detail=f"No evidence is within {max_age} day(s) of as_of",
                )

        else:
            return PrecheckService._base_item(
                rule,
                PrecheckResultType.RULE_ERROR,
                evidence_count=len(qualified),
                detail=f"Rule type {rule_type} has no typed evaluator",
            )

        return PrecheckService._base_item(
            rule,
            PrecheckResultType.PASS,
            evidence_count=len(qualified),
            detail=f"Typed rule {rule_type} satisfied with {len(qualified)} qualified evidence item(s)",
        )
