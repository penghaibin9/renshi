"""Deterministic HR15 input, rule, calculation and review services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_payroll.authority_registry import (
    EVENT_CALCULATION_COMPLETED,
    EVENT_REVIEW_COMPLETED,
)
from hr_payroll.calculation_models import (
    PayrollCalculationBatch,
    PayrollCalculationLine,
    PayrollInputSnapshot,
    PayrollReviewFact,
    SalaryRuleVersion,
)
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.services.input_fact_provider_registry import (
    REQUIRED_INPUT_AUTHORITIES,
    PayrollInputProviderRegistry,
    PayrollInputProviderRegistryError,
)
from hr_payroll.statutory_models import StatutoryContributionFact
from hr_payroll.services.statutory_contribution_service import (
    StatutoryContributionError,
    StatutoryContributionService,
)


class PayrollCalculationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PayrollCalculationOutcome:
    batch: PayrollCalculationBatch
    result_ids: tuple[str, ...]


REQUIRED_SOURCE_AUTHORITIES = REQUIRED_INPUT_AUTHORITIES
INPUT_SNAPSHOT_VERSION = "hr15-payroll-input-v2"
ROUNDING_MODES = {
    "HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
    "DOWN": ROUND_DOWN,
}
MONEY_QUANTUM = Decimal("0.01")


def _hash(payload) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value):
    if isinstance(value, Mapping):
        return {str(key): _canonical_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json(item) for item in value]
    if isinstance(value, (Decimal, UUID, date, datetime)):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _snapshot_hash_payload(snapshot: PayrollInputSnapshot) -> dict:
    return {
        "snapshotVersion": snapshot.snapshot_version,
        "periodId": str(snapshot.payroll_period_id),
        "staffId": str(snapshot.staff_id),
        "currencyCode": snapshot.currency_code,
        "sources": snapshot.source_versions_json,
        "variables": snapshot.variables_json,
    }


def verify_payroll_input_snapshot(snapshot: PayrollInputSnapshot) -> None:
    if snapshot.snapshot_version != INPUT_SNAPSHOT_VERSION:
        raise PayrollCalculationError(
            "PAYROLL_INPUT_SNAPSHOT_UNTRUSTED",
            "payroll input was not captured through the trusted provider boundary",
        )
    sources = snapshot.source_versions_json
    variables = snapshot.variables_json
    if not isinstance(sources, Mapping) or not isinstance(variables, Mapping):
        raise PayrollCalculationError(
            "PAYROLL_INPUT_SNAPSHOT_TAMPERED", "payroll input snapshot is malformed"
        )
    missing = REQUIRED_SOURCE_AUTHORITIES - set(sources)
    if missing:
        raise PayrollCalculationError(
            "PAYROLL_INPUT_SNAPSHOT_TAMPERED",
            "payroll input source evidence is incomplete",
        )
    merged_variables = {}
    for authority, source in sources.items():
        if not isinstance(source, Mapping):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_SNAPSHOT_TAMPERED", "payroll input source evidence is malformed"
            )
        source_variables = source.get("variables")
        source_snapshot = source.get("snapshot")
        if (
            not source.get("version")
            or not source.get("evidenceId")
            or not source.get("evidenceHash")
            or not isinstance(source_variables, Mapping)
            or not isinstance(source_snapshot, Mapping)
        ):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_SNAPSHOT_TAMPERED", "payroll input source evidence is incomplete"
            )
        evidence_payload = {
            "authority": authority,
            "tenantId": int(snapshot.tenant_id),
            "periodId": str(snapshot.payroll_period_id),
            "staffId": str(snapshot.staff_id),
            "version": source["version"],
            "evidenceId": source["evidenceId"],
            "snapshot": source_snapshot,
            "variables": source_variables,
        }
        if source["evidenceHash"] != _hash(evidence_payload):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_SNAPSHOT_TAMPERED", "payroll input source hash is invalid"
            )
        for key, value in source_variables.items():
            if key in merged_variables and merged_variables[key] != value:
                raise PayrollCalculationError(
                    "PAYROLL_INPUT_SNAPSHOT_TAMPERED",
                    "payroll input sources contain conflicting variables",
                )
            merged_variables[key] = value
    if merged_variables != dict(variables):
        raise PayrollCalculationError(
            "PAYROLL_INPUT_SNAPSHOT_TAMPERED",
            "payroll input variables do not match their source evidence",
        )
    if snapshot.content_hash != _hash(_snapshot_hash_payload(snapshot)):
        raise PayrollCalculationError(
            "PAYROLL_INPUT_SNAPSHOT_TAMPERED", "payroll input content hash is invalid"
        )


def verify_payroll_result_input_evidence(result: PayrollResultFact) -> PayrollInputSnapshot:
    line_evidence = list(
        PayrollCalculationLine.objects.filter(
            tenant_id=result.tenant_id,
            payroll_result_id=result.id,
        ).values_list("explanation_json", flat=True)
    )
    if not line_evidence or any(
        not isinstance(explanation, Mapping)
        or not explanation.get("inputSnapshotId")
        or not explanation.get("inputContentHash")
        for explanation in line_evidence
    ):
        raise PayrollCalculationError(
            "PAYROLL_INPUT_EVIDENCE_REQUIRED",
            "every payroll calculation line must reference trusted input evidence",
        )
    references = {
        (
            str(explanation.get("inputSnapshotId") or ""),
            str(explanation.get("inputContentHash") or ""),
        )
        for explanation in line_evidence
        if isinstance(explanation, Mapping)
    }
    if len(references) != 1:
        raise PayrollCalculationError(
            "PAYROLL_INPUT_EVIDENCE_REQUIRED",
            "payroll result has no unambiguous trusted input snapshot",
        )
    snapshot_id, expected_hash = references.pop()
    if not snapshot_id or not expected_hash:
        raise PayrollCalculationError(
            "PAYROLL_INPUT_EVIDENCE_REQUIRED",
            "payroll result input evidence is incomplete",
        )
    snapshot = PayrollInputSnapshot.objects.filter(
        id=snapshot_id,
        tenant_id=result.tenant_id,
        payroll_period_id=result.payroll_period_id,
        staff_id=result.staff_id,
    ).first()
    if snapshot is None:
        raise PayrollCalculationError(
            "PAYROLL_INPUT_EVIDENCE_REQUIRED",
            "payroll result input snapshot is unavailable in this tenant",
        )
    verify_payroll_input_snapshot(snapshot)
    if snapshot.content_hash != expected_hash:
        raise PayrollCalculationError(
            "PAYROLL_INPUT_SNAPSHOT_TAMPERED",
            "payroll result points to a different input snapshot hash",
        )
    return snapshot


def _decimal(value, *, code: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise PayrollCalculationError(code, "amount must be a decimal value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayrollCalculationError(code, "amount must be a decimal value") from exc
    if not result.is_finite():
        raise PayrollCalculationError(code, "amount must be finite")
    return result


class PayrollRuleService:
    def __init__(self, tenant_id: int, actor_user_id: int | None = None):
        if not tenant_id:
            raise PayrollCalculationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def create_draft(
        self,
        *,
        rule_code: str,
        version_no: int,
        item_code: str,
        name: str,
        item_type: str,
        formula: dict,
        effective_from,
        dependencies: list | None = None,
        priority: int = 100,
        currency_code: str = "CNY",
        rounding_mode: str = "HALF_UP",
        effective_to=None,
    ) -> SalaryRuleVersion:
        rule_code = str(rule_code or "").strip()
        item_code = str(item_code or "").strip()
        name = str(name or "").strip()
        if not rule_code or not item_code or not name:
            raise PayrollCalculationError(
                "SALARY_RULE_FIELDS_REQUIRED", "rule_code, item_code and name are required"
            )
        if item_type not in SalaryRuleVersion.ItemType.values:
            raise PayrollCalculationError(
                "SALARY_RULE_ITEM_TYPE_INVALID", "salary item type is invalid"
            )
        try:
            version_no = int(version_no)
            priority = int(priority)
        except (TypeError, ValueError) as exc:
            raise PayrollCalculationError(
                "SALARY_RULE_NUMBER_INVALID", "version and priority must be integers"
            ) from exc
        if version_no < 1 or priority < 0:
            raise PayrollCalculationError(
                "SALARY_RULE_NUMBER_INVALID", "version must be positive and priority non-negative"
            )
        if effective_to is not None and effective_to <= effective_from:
            raise PayrollCalculationError(
                "SALARY_RULE_EFFECTIVE_RANGE_INVALID", "effective_to must follow effective_from"
            )
        rule = SalaryRuleVersion(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            rule_code=rule_code,
            version_no=version_no,
            item_code=item_code,
            name=name,
            item_type=item_type,
            priority=priority,
            currency_code=str(currency_code or "").upper(),
            formula_json=formula,
            dependencies_json=dependencies or [],
            rounding_mode=rounding_mode,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        self._validate_formula(rule)
        rule.save()
        return rule

    @transaction.atomic
    def publish(self, rule_id) -> SalaryRuleVersion:
        rule = (
            SalaryRuleVersion.objects.select_for_update()
            .filter(id=rule_id, tenant_id=self.tenant_id)
            .first()
        )
        if rule is None:
            raise PayrollCalculationError("SALARY_RULE_NOT_FOUND", "salary rule not found")
        if rule.status == SalaryRuleVersion.Status.PUBLISHED:
            return rule
        if rule.status != SalaryRuleVersion.Status.DRAFT:
            raise PayrollCalculationError(
                "SALARY_RULE_INVALID_STATE", "only a draft salary rule can be published"
            )
        self._validate_formula(rule)
        payload = {
            "ruleCode": rule.rule_code,
            "versionNo": rule.version_no,
            "itemCode": rule.item_code,
            "itemType": rule.item_type,
            "priority": rule.priority,
            "currencyCode": rule.currency_code,
            "formula": rule.formula_json,
            "dependencies": rule.dependencies_json,
            "roundingMode": rule.rounding_mode,
            "effectiveFrom": rule.effective_from,
            "effectiveTo": rule.effective_to,
        }
        rule.content_hash = _hash(payload)
        rule.status = SalaryRuleVersion.Status.PUBLISHED
        rule.published_at = timezone.now()
        rule.updated_by = self.actor_user_id
        rule.save(
            update_fields=[
                "content_hash",
                "status",
                "published_at",
                "updated_by",
                "updated_at",
            ]
        )
        return rule

    @staticmethod
    def _validate_formula(rule: SalaryRuleVersion) -> None:
        formula = rule.formula_json
        if not isinstance(formula, dict):
            raise PayrollCalculationError(
                "SALARY_RULE_FORMULA_INVALID", "formula must be an object"
            )
        op = str(formula.get("op", "")).upper()
        if op not in {"INPUT", "FIXED", "PERCENT", "SUM"}:
            raise PayrollCalculationError(
                "SALARY_RULE_OPERATION_UNSUPPORTED", f"unsupported formula operation: {op}"
            )
        if rule.rounding_mode not in ROUNDING_MODES:
            raise PayrollCalculationError(
                "SALARY_RULE_ROUNDING_UNSUPPORTED", "unsupported rounding mode"
            )
        dependencies = rule.dependencies_json
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) and value for value in dependencies
        ):
            raise PayrollCalculationError(
                "SALARY_RULE_DEPENDENCIES_INVALID", "dependencies must be item-code strings"
            )
        if len(set(dependencies)) != len(dependencies) or rule.item_code in dependencies:
            raise PayrollCalculationError(
                "SALARY_RULE_DEPENDENCIES_INVALID", "dependencies must be unique and non-recursive"
            )
        if op == "INPUT" and not formula.get("key"):
            raise PayrollCalculationError("SALARY_RULE_INPUT_KEY_REQUIRED", "input key is required")
        if op == "FIXED":
            _decimal(formula.get("amount"), code="SALARY_RULE_AMOUNT_INVALID")
        if op == "PERCENT":
            if not formula.get("base"):
                raise PayrollCalculationError("SALARY_RULE_BASE_REQUIRED", "percentage base is required")
            _decimal(formula.get("rate"), code="SALARY_RULE_RATE_INVALID")
        if op == "SUM" and not dependencies:
            raise PayrollCalculationError(
                "SALARY_RULE_DEPENDENCY_REQUIRED", "SUM requires at least one dependency"
            )


class PayrollCalculationService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: int | None = None,
        correlation_id: str = "",
    ):
        if not tenant_id:
            raise PayrollCalculationError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id
        self.correlation_id = correlation_id

    def capture_input(
        self,
        *,
        period_id,
        staff_id,
    ) -> PayrollInputSnapshot:
        period = PayrollPeriod.objects.filter(
            id=period_id, tenant_id=self.tenant_id
        ).first()
        if period is None:
            raise PayrollCalculationError("PAYROLL_PERIOD_NOT_FOUND", "payroll period not found")
        if period.status != PayrollPeriod.Status.INPUT_FROZEN:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_NOT_FROZEN",
                "input snapshots can only be captured for an input-frozen period",
            )
        profile = self._effective_payroll_profile(period=period, staff_id=staff_id)
        try:
            providers = PayrollInputProviderRegistry.resolve_all()
        except PayrollInputProviderRegistryError as exc:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROVIDER_UNAVAILABLE", str(exc)
            ) from exc
        required_variables = self._required_variable_keys(period)
        request = {
            "schemaVersion": "hr15.payroll-input-request.2",
            "tenantId": self.tenant_id,
            "periodId": str(period.id),
            "periodCode": period.period_code,
            "staffId": str(staff_id),
            "startDate": period.start_date.isoformat(),
            "endDate": period.end_date.isoformat(),
            "asOf": period.end_date.isoformat(),
            "requiredVariableKeys": sorted(required_variables),
            "correlationId": self.correlation_id,
        }
        source_versions = {}
        variables = {}
        for authority, provider in providers:
            provider_request = {**request, "authority": authority}
            try:
                raw = provider.collect(dict(provider_request))
            except Exception as exc:
                raise PayrollCalculationError(
                    "PAYROLL_INPUT_PROVIDER_UNAVAILABLE",
                    f"trusted payroll input provider {authority} is unavailable",
                ) from exc
            source, provider_variables = self._normalize_provider_result(
                authority=authority,
                request=provider_request,
                raw=raw,
            )
            source_versions[authority] = source
            for key, value in provider_variables.items():
                if key in variables and variables[key] != value:
                    raise PayrollCalculationError(
                        "PAYROLL_INPUT_PROVIDER_CONTRACT_INVALID",
                        f"trusted providers disagree on payroll variable {key}",
                    )
                variables[key] = value

        missing_variables = sorted(required_variables - set(variables))
        if missing_variables:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROVIDER_INCOMPLETE",
                "trusted providers did not supply required variables: "
                + ",".join(missing_variables),
            )
        for key in required_variables:
            _decimal(variables[key], code="PAYROLL_INPUT_VALUE_INVALID")
        return self._persist_input_snapshot(
            period=period,
            staff_id=staff_id,
            currency_code=str(profile.currency_code).strip().upper(),
            source_versions=source_versions,
            variables=variables,
        )

    def _effective_payroll_profile(self, *, period, staff_id) -> PayrollProfile:
        profiles = list(
            PayrollProfile.objects.filter(
                tenant_id=self.tenant_id,
                staff_id=staff_id,
                status=PayrollProfile.Status.ACTIVE,
                effective_from__lte=period.end_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=period.start_date))
            .order_by("-effective_from", "id")[:2]
        )
        if not profiles:
            raise PayrollCalculationError(
                "PAYROLL_PROFILE_NOT_FOUND",
                "no effective payroll profile exists for this staff and tenant",
            )
        if len(profiles) > 1:
            raise PayrollCalculationError(
                "PAYROLL_PROFILE_OVERLAP",
                "multiple payroll profiles are effective for this staff and period",
            )
        currency_code = str(profiles[0].currency_code or "").strip().upper()
        if len(currency_code) != 3:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_CURRENCY_INVALID",
                "effective payroll profile has an invalid currency",
            )
        return profiles[0]

    def _required_variable_keys(self, period) -> set[str]:
        rules = list(
            SalaryRuleVersion.objects.filter(
                tenant_id=self.tenant_id,
                status=SalaryRuleVersion.Status.PUBLISHED,
                effective_from__lte=period.end_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=period.start_date))
            .order_by("priority", "item_code", "version_no")
        )
        for rule in rules:
            PayrollRuleService._validate_formula(rule)
        item_codes = {rule.item_code for rule in rules}
        required = {
            str(rule.formula_json["key"])
            for rule in rules
            if str(rule.formula_json.get("op", "")).upper() == "INPUT"
        }
        required.update(
            str(rule.formula_json["base"])
            for rule in rules
            if str(rule.formula_json.get("op", "")).upper() == "PERCENT"
            and rule.formula_json.get("base") not in item_codes
        )
        statutory = StatutoryContributionService(self.tenant_id).effective_rules(period)
        required.update(str(rule.base_variable_key) for rule in statutory)
        return required

    def _normalize_provider_result(self, *, authority, request, raw):
        if not isinstance(raw, Mapping):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROVIDER_CONTRACT_INVALID",
                f"trusted payroll input provider {authority} must return an object",
            )
        expected = {
            "authority": authority,
            "tenantId": self.tenant_id,
            "periodId": request["periodId"],
            "staffId": request["staffId"],
        }
        if any(str(raw.get(key)) != str(value) for key, value in expected.items()):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROVIDER_CONTRACT_INVALID",
                f"trusted payroll input provider {authority} returned mismatched identity",
            )
        version = str(raw.get("version") or "").strip()
        evidence_id = str(raw.get("evidenceId") or "").strip()
        snapshot = raw.get("snapshot")
        provider_variables = raw.get("variables")
        if (
            not version
            or not evidence_id
            or not isinstance(snapshot, Mapping)
            or not isinstance(provider_variables, Mapping)
        ):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROVIDER_CONTRACT_INVALID",
                f"trusted payroll input provider {authority} returned incomplete evidence",
            )
        if not all(isinstance(key, str) and key for key in provider_variables):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROVIDER_CONTRACT_INVALID",
                f"trusted payroll input provider {authority} returned invalid variable keys",
            )
        canonical_snapshot = _canonical_json(snapshot)
        canonical_variables = _canonical_json(provider_variables)
        evidence_payload = {
            **expected,
            "version": version,
            "evidenceId": evidence_id,
            "snapshot": canonical_snapshot,
            "variables": canonical_variables,
        }
        source = {
            "version": version,
            "evidenceId": evidence_id,
            "evidenceHash": _hash(evidence_payload),
            "snapshot": canonical_snapshot,
            "variables": canonical_variables,
        }
        return source, canonical_variables

    @transaction.atomic
    def _persist_input_snapshot(
        self, *, period, staff_id, currency_code, source_versions, variables
    ):
        locked_period = PayrollPeriod.objects.select_for_update().filter(
            id=period.id, tenant_id=self.tenant_id
        ).first()
        if locked_period is None:
            raise PayrollCalculationError("PAYROLL_PERIOD_NOT_FOUND", "payroll period not found")
        if locked_period.status != PayrollPeriod.Status.INPUT_FROZEN:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_NOT_FROZEN",
                "input snapshots can only be captured for an input-frozen period",
            )
        if (
            locked_period.start_date != period.start_date
            or locked_period.end_date != period.end_date
            or locked_period.period_code != period.period_code
        ):
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PERIOD_CHANGED",
                "payroll period changed while trusted provider facts were collected",
            )
        locked_profile = self._effective_payroll_profile(
            period=locked_period, staff_id=staff_id
        )
        if str(locked_profile.currency_code).strip().upper() != currency_code:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_PROFILE_CHANGED",
                "payroll profile changed while trusted provider facts were collected",
            )
        payload = {
            "snapshotVersion": INPUT_SNAPSHOT_VERSION,
            "periodId": str(locked_period.id),
            "staffId": str(staff_id),
            "currencyCode": currency_code,
            "sources": source_versions,
            "variables": variables,
        }
        content_hash = _hash(payload)
        existing = PayrollInputSnapshot.objects.filter(
            tenant_id=self.tenant_id,
            payroll_period_id=locked_period.id,
            staff_id=staff_id,
        ).first()
        if existing:
            verify_payroll_input_snapshot(existing)
            if existing.content_hash != content_hash:
                raise PayrollCalculationError(
                    "PAYROLL_INPUT_IDEMPOTENCY_CONFLICT",
                    "staff input was already frozen with different content",
                )
            return existing
        return PayrollInputSnapshot.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            payroll_period_id=locked_period.id,
            staff_id=staff_id,
            currency_code=currency_code,
            snapshot_version=INPUT_SNAPSHOT_VERSION,
            source_versions_json=source_versions,
            variables_json=variables,
            content_hash=content_hash,
            captured_at=timezone.now(),
        )

    def _effective_rules(self, period: PayrollPeriod) -> list[SalaryRuleVersion]:
        rules = list(
            SalaryRuleVersion.objects.filter(
                tenant_id=self.tenant_id,
                status=SalaryRuleVersion.Status.PUBLISHED,
                effective_from__lte=period.end_date,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=period.start_date))
            .order_by("priority", "item_code", "version_no")
        )
        if not rules:
            raise PayrollCalculationError(
                "PAYROLL_RULE_SET_EMPTY", "no published salary rule is effective for the period"
            )
        by_item: dict[str, SalaryRuleVersion] = {}
        for rule in rules:
            PayrollRuleService._validate_formula(rule)
            if rule.item_code in by_item:
                raise PayrollCalculationError(
                    "PAYROLL_RULE_SET_OVERLAP",
                    f"multiple effective versions found for item {rule.item_code}",
                )
            by_item[rule.item_code] = rule
        return self._sort_rules(by_item)

    @staticmethod
    def _sort_rules(by_item: dict[str, SalaryRuleVersion]) -> list[SalaryRuleVersion]:
        visiting: set[str] = set()
        visited: set[str] = set()
        result: list[SalaryRuleVersion] = []

        def visit(item_code: str) -> None:
            if item_code in visiting:
                raise PayrollCalculationError(
                    "PAYROLL_RULE_DEPENDENCY_CYCLE", f"rule dependency cycle at {item_code}"
                )
            if item_code in visited:
                return
            visiting.add(item_code)
            rule = by_item[item_code]
            for dependency in rule.dependencies_json:
                if dependency not in by_item:
                    raise PayrollCalculationError(
                        "PAYROLL_RULE_DEPENDENCY_MISSING",
                        f"rule {item_code} depends on missing item {dependency}",
                    )
                visit(dependency)
            visiting.remove(item_code)
            visited.add(item_code)
            result.append(rule)

        for code in sorted(by_item, key=lambda value: (by_item[value].priority, value)):
            visit(code)
        return result

    @staticmethod
    def _evaluate_rule(
        rule: SalaryRuleVersion,
        variables: dict,
        calculated: dict[str, Decimal],
    ) -> tuple[Decimal, dict]:
        formula = rule.formula_json
        op = str(formula["op"]).upper()
        explanation: dict = {"operation": op, "dependencies": list(rule.dependencies_json)}
        if op == "INPUT":
            key = formula["key"]
            if key not in variables:
                raise PayrollCalculationError(
                    "PAYROLL_INPUT_VALUE_MISSING", f"input value {key} is missing"
                )
            amount = _decimal(variables[key], code="PAYROLL_INPUT_VALUE_INVALID")
            explanation["inputKey"] = key
            explanation["inputValue"] = str(amount)
        elif op == "FIXED":
            amount = _decimal(formula["amount"], code="SALARY_RULE_AMOUNT_INVALID")
            explanation["fixedAmount"] = str(amount)
        elif op == "PERCENT":
            base_code = formula["base"]
            if base_code in calculated:
                base = calculated[base_code]
                explanation["baseKind"] = "ITEM"
            elif base_code in variables:
                base = _decimal(variables[base_code], code="PAYROLL_INPUT_VALUE_INVALID")
                explanation["baseKind"] = "INPUT"
            else:
                raise PayrollCalculationError(
                    "PAYROLL_RULE_BASE_MISSING", f"percentage base {base_code} is unavailable"
                )
            rate = _decimal(formula["rate"], code="SALARY_RULE_RATE_INVALID")
            amount = base * rate
            explanation.update({"base": base_code, "baseAmount": str(base), "rate": str(rate)})
        else:  # SUM
            amount = sum((calculated[value] for value in rule.dependencies_json), Decimal("0"))
            explanation["componentAmounts"] = {
                value: str(calculated[value]) for value in rule.dependencies_json
            }
        rounded = amount.quantize(MONEY_QUANTUM, rounding=ROUNDING_MODES[rule.rounding_mode])
        explanation.update(
            {
                "unroundedAmount": str(amount),
                "roundingMode": rule.rounding_mode,
                "roundedAmount": str(rounded),
                "ruleContentHash": rule.content_hash,
            }
        )
        return rounded, explanation

    @transaction.atomic
    def calculate(
        self, *, period_id, batch_no: str, idempotency_key: str
    ) -> PayrollCalculationOutcome:
        if not batch_no or not idempotency_key:
            raise PayrollCalculationError(
                "PAYROLL_CALCULATION_IDEMPOTENCY_REQUIRED",
                "batch_no and idempotency_key are required",
            )
        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None:
            raise PayrollCalculationError("PAYROLL_PERIOD_NOT_FOUND", "payroll period not found")

        existing = PayrollCalculationBatch.objects.select_for_update().filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            if existing.payroll_period_id != period.id or existing.batch_no != batch_no:
                raise PayrollCalculationError(
                    "PAYROLL_CALCULATION_IDEMPOTENCY_CONFLICT",
                    "idempotency key belongs to another calculation request",
                )
            if existing.status != PayrollCalculationBatch.Status.COMPLETED:
                raise PayrollCalculationError(
                    "PAYROLL_CALCULATION_IN_PROGRESS",
                    "calculation request has not completed",
                )
            ids = tuple(
                str(value)
                for value in PayrollCalculationLine.objects.filter(
                    tenant_id=self.tenant_id,
                    calculation_batch_id=existing.id,
                )
                .order_by("payroll_result_id")
                .values_list("payroll_result_id", flat=True)
                .distinct()
            )
            results = list(
                PayrollResultFact.objects.filter(
                    tenant_id=self.tenant_id,
                    payroll_period_id=period.id,
                    id__in=ids,
                )
            )
            if not ids or len(results) != len(ids) or existing.result_count != len(ids):
                raise PayrollCalculationError(
                    "PAYROLL_INPUT_EVIDENCE_REQUIRED",
                    "completed calculation results are incomplete",
                )
            for result in results:
                verify_payroll_result_input_evidence(result)
            return PayrollCalculationOutcome(existing, ids)

        if period.status != PayrollPeriod.Status.INPUT_FROZEN:
            raise PayrollCalculationError(
                "PAYROLL_PERIOD_NOT_INPUT_FROZEN",
                f"period status {period.status} cannot be calculated",
            )
        if PayrollResultFact.objects.filter(
            tenant_id=self.tenant_id, payroll_period_id=period.id
        ).exists():
            raise PayrollCalculationError(
                "PAYROLL_PERIOD_RESULT_CONFLICT",
                "period already contains payroll results",
            )

        rules = self._effective_rules(period)
        statutory_service = StatutoryContributionService(
            self.tenant_id,
            actor_user_id=self.actor_user_id,
            correlation_id=self.correlation_id,
        )
        try:
            statutory_rules = statutory_service.effective_rules(period)
        except StatutoryContributionError as exc:
            raise PayrollCalculationError(exc.code, str(exc)) from exc
        salary_item_codes = {rule.item_code for rule in rules}
        statutory_item_codes = [
            item_code
            for rule in statutory_rules
            for item_code in (rule.employee_item_code, rule.employer_item_code)
        ]
        if len(statutory_item_codes) != len(set(statutory_item_codes)) or salary_item_codes.intersection(
            statutory_item_codes
        ):
            raise PayrollCalculationError(
                "STATUTORY_ITEM_CODE_CONFLICT",
                "statutory employee/employer item codes must be unique in the payroll rule set",
            )
        rule_set_hash = _hash(
            {
                "salary": [rule.content_hash for rule in rules],
                "statutory": [rule.content_hash for rule in statutory_rules],
            }
        )
        snapshots = list(
            PayrollInputSnapshot.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, payroll_period_id=period.id)
            .order_by("staff_id")
        )
        if not snapshots:
            raise PayrollCalculationError(
                "PAYROLL_INPUT_SNAPSHOT_REQUIRED", "period has no frozen staff input"
            )
        for snapshot in snapshots:
            verify_payroll_input_snapshot(snapshot)

        batch = PayrollCalculationBatch.objects.create(
            tenant_id=self.tenant_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
            payroll_period_id=period.id,
            batch_no=batch_no,
            idempotency_key=idempotency_key,
            rule_set_hash=rule_set_hash,
            status=PayrollCalculationBatch.Status.RUNNING,
            staff_count=len(snapshots),
            started_at=timezone.now(),
        )
        gross_total = Decimal("0.00")
        deduction_total = Decimal("0.00")
        net_total = Decimal("0.00")
        result_ids: list[str] = []
        for snapshot in snapshots:
            calculated: dict[str, Decimal] = {}
            evaluated: list[tuple[SalaryRuleVersion, Decimal, dict]] = []
            for rule in rules:
                if rule.currency_code != snapshot.currency_code:
                    raise PayrollCalculationError(
                        "PAYROLL_RULE_CURRENCY_MISMATCH",
                        f"rule {rule.item_code} currency does not match staff input",
                    )
                amount, explanation = self._evaluate_rule(
                    rule, snapshot.variables_json, calculated
                )
                calculated[rule.item_code] = amount
                evaluated.append((rule, amount, explanation))
            try:
                statutory_calculated = [
                    statutory_service.calculate(rule, snapshot.variables_json)
                    for rule in statutory_rules
                ]
            except StatutoryContributionError as exc:
                raise PayrollCalculationError(exc.code, str(exc)) from exc
            gross = sum(
                (amount for rule, amount, _ in evaluated if rule.item_type == rule.ItemType.EARNING),
                Decimal("0.00"),
            )
            deduction = sum(
                (amount for rule, amount, _ in evaluated if rule.item_type == rule.ItemType.DEDUCTION),
                Decimal("0.00"),
            )
            deduction += sum(
                (item.employee_amount for item in statutory_calculated), Decimal("0.00")
            )
            net = (gross - deduction).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            if net < 0:
                raise PayrollCalculationError(
                    "PAYROLL_RESULT_NEGATIVE_NET",
                    f"calculated net amount is negative for staff {snapshot.staff_id}",
                )
            result_no = f"PAY-{period.period_code[:24]}-{snapshot.staff_id.hex[:12]}"
            result = PayrollResultFact.objects.create(
                tenant_id=self.tenant_id,
                created_by=self.actor_user_id,
                updated_by=self.actor_user_id,
                result_no=result_no,
                payroll_period_id=period.id,
                staff_id=snapshot.staff_id,
                currency_code=snapshot.currency_code,
                gross_amount=gross,
                deduction_amount=deduction,
                net_amount=net,
                status=PayrollResultFact.Status.DRAFT,
            )
            salary_lines = [
                    PayrollCalculationLine(
                        tenant_id=self.tenant_id,
                        created_by=self.actor_user_id,
                        updated_by=self.actor_user_id,
                        calculation_batch_id=batch.id,
                        payroll_result_id=result.id,
                        staff_id=snapshot.staff_id,
                        item_code=rule.item_code,
                        item_name=rule.name,
                        item_type=rule.item_type,
                        sequence_no=sequence,
                        amount=amount,
                        currency_code=rule.currency_code,
                        rule_version_id=rule.id,
                        explanation_json={
                            **explanation,
                            "inputSnapshotId": str(snapshot.id),
                            "inputContentHash": snapshot.content_hash,
                        },
                    )
                    for sequence, (rule, amount, explanation) in enumerate(evaluated, 1)
                ]
            statutory_lines = []
            next_sequence = len(salary_lines) + 1
            for item in statutory_calculated:
                fact = statutory_service.create_fact(
                    calculated=item,
                    period=period,
                    result=result,
                    batch=batch,
                    snapshot=snapshot,
                )
                common_explanation = {
                    "authority": "HR15_STATUTORY_CONTRIBUTION",
                    "contributionFactId": str(fact.id),
                    "contributionCode": fact.contribution_code,
                    "contributionGroup": fact.contribution_group,
                    "requestedBase": str(fact.requested_base),
                    "contributionBase": str(fact.contribution_base),
                    "ruleContentHash": fact.rule_content_hash,
                    "inputSnapshotId": str(snapshot.id),
                    "inputContentHash": snapshot.content_hash,
                    "evidenceHash": fact.evidence_hash,
                }
                statutory_lines.extend(
                    (
                        PayrollCalculationLine(
                            tenant_id=self.tenant_id,
                            created_by=self.actor_user_id,
                            updated_by=self.actor_user_id,
                            calculation_batch_id=batch.id,
                            payroll_result_id=result.id,
                            staff_id=snapshot.staff_id,
                            item_code=fact.employee_item_code,
                            item_name=f"{item.rule.name}（个人）",
                            item_type=SalaryRuleVersion.ItemType.DEDUCTION,
                            sequence_no=next_sequence,
                            amount=fact.employee_amount,
                            currency_code=snapshot.currency_code,
                            rule_version_id=item.rule.id,
                            explanation_json={
                                **common_explanation,
                                "payer": "EMPLOYEE",
                                "rate": str(fact.employee_rate),
                            },
                        ),
                        PayrollCalculationLine(
                            tenant_id=self.tenant_id,
                            created_by=self.actor_user_id,
                            updated_by=self.actor_user_id,
                            calculation_batch_id=batch.id,
                            payroll_result_id=result.id,
                            staff_id=snapshot.staff_id,
                            item_code=fact.employer_item_code,
                            item_name=f"{item.rule.name}（单位）",
                            item_type=SalaryRuleVersion.ItemType.EMPLOYER,
                            sequence_no=next_sequence + 1,
                            amount=fact.employer_amount,
                            currency_code=snapshot.currency_code,
                            rule_version_id=item.rule.id,
                            explanation_json={
                                **common_explanation,
                                "payer": "EMPLOYER",
                                "rate": str(fact.employer_rate),
                            },
                        ),
                    )
                )
                next_sequence += 2
            PayrollCalculationLine.objects.bulk_create(salary_lines + statutory_lines)
            gross_total += gross
            deduction_total += deduction
            net_total += net
            result_ids.append(str(result.id))

        batch.status = PayrollCalculationBatch.Status.COMPLETED
        batch.result_count = len(result_ids)
        batch.gross_total = gross_total
        batch.deduction_total = deduction_total
        batch.net_total = net_total
        batch.completed_at = timezone.now()
        batch.updated_by = self.actor_user_id
        batch.save(
            update_fields=[
                "status",
                "result_count",
                "gross_total",
                "deduction_total",
                "net_total",
                "completed_at",
                "updated_by",
                "updated_at",
            ]
        )
        period.status = PayrollPeriod.Status.CALCULATED
        period.updated_by = self.actor_user_id
        period.save(update_fields=["status", "updated_by", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_CALCULATION_COMPLETED,
            payload={
                "batchId": str(batch.id),
                "periodId": str(period.id),
                "ruleSetHash": rule_set_hash,
                "staffCount": batch.staff_count,
                "resultCount": batch.result_count,
                "grossTotal": str(batch.gross_total),
                "deductionTotal": str(batch.deduction_total),
                "netTotal": str(batch.net_total),
                "completedAt": batch.completed_at.isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return PayrollCalculationOutcome(batch, tuple(result_ids))

    @transaction.atomic
    def review_result(self, *, result_id, decision: str, note: str = "") -> PayrollReviewFact:
        result = (
            PayrollResultFact.objects.select_for_update()
            .filter(id=result_id, tenant_id=self.tenant_id)
            .first()
        )
        if result is None:
            raise PayrollCalculationError("PAYROLL_RESULT_NOT_FOUND", "payroll result not found")
        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=result.payroll_period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None or period.status != PayrollPeriod.Status.CALCULATED:
            raise PayrollCalculationError(
                "PAYROLL_PERIOD_NOT_CALCULATED", "result is not in a calculated period"
            )
        if decision not in PayrollReviewFact.Decision.values:
            raise PayrollCalculationError(
                "PAYROLL_REVIEW_DECISION_INVALID", "review decision is invalid"
            )
        if not self.actor_user_id:
            raise PayrollCalculationError(
                "PAYROLL_REVIEW_ACTOR_REQUIRED", "review actor is required"
            )
        existing = PayrollReviewFact.objects.filter(
            tenant_id=self.tenant_id, payroll_result_id=result.id
        ).first()
        if existing:
            if existing.decision != decision or existing.note != (note or ""):
                raise PayrollCalculationError(
                    "PAYROLL_REVIEW_IDEMPOTENCY_CONFLICT",
                    "result already has another immutable review",
                )
            review = existing
        else:
            review = PayrollReviewFact.objects.create(
                tenant_id=self.tenant_id,
                created_by=self.actor_user_id,
                updated_by=self.actor_user_id,
                payroll_period_id=period.id,
                payroll_result_id=result.id,
                decision=decision,
                note=note or "",
                reviewed_by=self.actor_user_id,
                reviewed_at=timezone.now(),
            )
        try:
            StatutoryContributionService(
                self.tenant_id,
                actor_user_id=self.actor_user_id,
                correlation_id=self.correlation_id,
            ).review_for_result(result_id=result.id, review=review)
        except StatutoryContributionError as exc:
            raise PayrollCalculationError(exc.code, str(exc)) from exc
        return review

    @transaction.atomic
    def complete_review(self, *, period_id) -> PayrollPeriod:
        period = (
            PayrollPeriod.objects.select_for_update()
            .filter(id=period_id, tenant_id=self.tenant_id)
            .first()
        )
        if period is None:
            raise PayrollCalculationError("PAYROLL_PERIOD_NOT_FOUND", "payroll period not found")
        if period.status == PayrollPeriod.Status.REVIEWED:
            return period
        if period.status != PayrollPeriod.Status.CALCULATED:
            raise PayrollCalculationError(
                "PAYROLL_PERIOD_NOT_CALCULATED", "period is not ready for review completion"
            )
        result_ids = list(
            PayrollResultFact.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, payroll_period_id=period.id)
            .values_list("id", flat=True)
        )
        if not result_ids:
            raise PayrollCalculationError(
                "PAYROLL_REVIEW_RESULTS_REQUIRED", "period has no payroll result"
            )
        approved_ids = set(
            PayrollReviewFact.objects.filter(
                tenant_id=self.tenant_id,
                payroll_result_id__in=result_ids,
                decision=PayrollReviewFact.Decision.APPROVED,
            ).values_list("payroll_result_id", flat=True)
        )
        if approved_ids != set(result_ids):
            raise PayrollCalculationError(
                "PAYROLL_REVIEW_INCOMPLETE",
                "every result requires one immutable approval before finalization",
            )
        if StatutoryContributionFact.objects.filter(
            tenant_id=self.tenant_id,
            payroll_period_id=period.id,
        ).exclude(status=StatutoryContributionFact.Status.REVIEWED).exists():
            raise PayrollCalculationError(
                "STATUTORY_REVIEW_INCOMPLETE",
                "every statutory contribution requires evidence-backed review",
            )
        period.status = PayrollPeriod.Status.REVIEWED
        period.updated_by = self.actor_user_id
        period.save(update_fields=["status", "updated_by", "updated_at"])
        emit_registered_event(
            tenant_id=self.tenant_id,
            event_name=EVENT_REVIEW_COMPLETED,
            payload={
                "periodId": str(period.id),
                "approvedResultIds": [str(value) for value in result_ids],
                "reviewedBy": self.actor_user_id,
                "completedAt": timezone.now().isoformat(),
            },
            correlation_id=self.correlation_id,
        )
        return period
