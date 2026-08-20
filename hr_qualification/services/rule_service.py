"""HR09 double-teacher rule authority service.

ACTIVE rule versions are immutable business authority. The v2 checksum covers
all fields that can affect an eligibility decision, including evidence
requirements; consumers can therefore detect post-publish drift before using a
rule version.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from hr_qualification.constants import (
    HardOrSoft,
    RulePackVersionStatus,
    RuleType,
)
from hr_qualification.models import (
    HrDoubleTeacherEvidenceRequirement,
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePackVersion,
)


CHECKSUM_PREFIX = "sha256:v2:"


class RulePackError(Exception):
    def __init__(self, code: str, message: str | None = None):
        if message is None:
            message = code
            code = "RULE_PACK_ERROR"
        self.code = code
        super().__init__(message)


class RuleService:
    """双师规则发布、继承与不可变完整性服务。"""

    @staticmethod
    def validate_inheritance(version: HrDoubleTeacherRulePackVersion) -> list[dict]:
        violations: list[dict] = []
        pack = version.rule_pack_id
        if not pack.parent_rule_pack_id:
            return violations

        try:
            parent_version = HrDoubleTeacherRulePackVersion.objects.filter(
                rule_pack_id=pack.parent_rule_pack_id,
                status=RulePackVersionStatus.ACTIVE,
            ).latest("version_no")
        except HrDoubleTeacherRulePackVersion.DoesNotExist:
            return violations

        child_rules = {
            r.rule_code: r
            for r in HrDoubleTeacherRule.objects.filter(version_id=version)
        }
        parent_rules = {
            r.rule_code: r
            for r in HrDoubleTeacherRule.objects.filter(version_id=parent_version)
        }

        for code, parent_rule in parent_rules.items():
            if parent_rule.hard_or_soft != HardOrSoft.HARD:
                continue
            child_rule = child_rules.get(code)
            if child_rule is None:
                violations.append(
                    {
                        "rule_code": code,
                        "dimension": parent_rule.dimension_code,
                        "level": parent_rule.level,
                        "violation": "HARD_RULE_REMOVED",
                        "description": f"父级 HARD Rule {code} 被删除。",
                    }
                )
                continue
            if child_rule.rule_type != parent_rule.rule_type:
                violations.append(
                    {
                        "rule_code": code,
                        "violation": "RULE_TYPE_CHANGED",
                        "description": f"规则类型从 {parent_rule.rule_type} 变为 {child_rule.rule_type}。",
                    }
                )
            if child_rule.hard_or_soft == HardOrSoft.SOFT:
                violations.append(
                    {
                        "rule_code": code,
                        "violation": "RULE_WEAKER_THAN_PARENT",
                        "description": f"父级 HARD Rule {code} 在本级被降为 SOFT。",
                    }
                )
        return violations

    @staticmethod
    def _requirement_payload(requirement: HrDoubleTeacherEvidenceRequirement) -> dict:
        return {
            "id": str(requirement.id),
            "evidenceCategory": requirement.evidence_category,
            "minCount": requirement.min_count,
            "minDuration": requirement.min_duration,
            "minLevel": requirement.min_level,
            "allowedSourceDomains": requirement.allowed_source_domains or [],
            "documentRequired": requirement.document_required,
            "verificationRequired": requirement.verification_required,
        }

    @classmethod
    def _rule_payload(cls, rule: HrDoubleTeacherRule) -> dict:
        requirements = list(
            HrDoubleTeacherEvidenceRequirement.objects.filter(rule_id=rule).order_by(
                "evidence_category", "min_count", "id"
            )
        )
        return {
            "id": str(rule.id),
            "ruleCode": rule.rule_code,
            "dimensionCode": rule.dimension_code,
            "level": rule.level,
            "ruleType": rule.rule_type,
            "operator": rule.operator,
            "expectedValue": rule.expected_value_json,
            "hardOrSoft": rule.hard_or_soft,
            "evidenceType": rule.evidence_type,
            "sourceProvider": rule.source_provider,
            "manualReviewRequired": rule.manual_review_required,
            "sequence": rule.sequence,
            "requirements": [cls._requirement_payload(req) for req in requirements],
        }

    @classmethod
    def version_payload(cls, version: HrDoubleTeacherRulePackVersion) -> dict:
        pack = version.rule_pack_id
        rules = list(
            HrDoubleTeacherRule.objects.filter(version_id=version).order_by(
                "sequence", "rule_code", "id"
            )
        )
        return {
            "schemaVersion": 2,
            "versionId": str(version.id),
            "rulePackId": str(pack.id),
            "rulePackTenantId": pack.tenant_id,
            "jurisdictionLevel": pack.jurisdiction_level,
            "jurisdictionCode": pack.jurisdiction_code,
            "parentRulePackId": (
                str(pack.parent_rule_pack_id_id) if pack.parent_rule_pack_id_id else None
            ),
            "versionNo": version.version_no,
            "effectiveFrom": version.effective_from.isoformat(),
            "effectiveTo": version.effective_to.isoformat() if version.effective_to else None,
            "policyDocumentIds": version.policy_document_ids or [],
            "rules": [cls._rule_payload(rule) for rule in rules],
        }

    @classmethod
    def compute_version_checksum(cls, version: HrDoubleTeacherRulePackVersion) -> str:
        payload = cls.version_payload(version)
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        return CHECKSUM_PREFIX + digest

    @classmethod
    def assert_version_integrity(
        cls,
        version: HrDoubleTeacherRulePackVersion,
    ) -> None:
        if version.status not in {
            RulePackVersionStatus.ACTIVE,
            RulePackVersionStatus.RETIRED,
        }:
            raise RulePackError(
                "RULE_VERSION_NOT_FORMAL",
                f"rule version status {version.status} is not formal authority",
            )
        if not str(version.checksum or "").startswith(CHECKSUM_PREFIX):
            raise RulePackError(
                "RULE_VERSION_CHECKSUM_LEGACY",
                "formal rule version does not carry a v2 full-authority checksum",
            )
        observed = cls.compute_version_checksum(version)
        if observed != version.checksum:
            raise RulePackError(
                "RULE_VERSION_INTEGRITY_DRIFT",
                "formal rule version content changed after publication",
            )

    @staticmethod
    def _number(value) -> Decimal | None:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @classmethod
    def validate_typed_rules(cls, version: HrDoubleTeacherRulePackVersion) -> list[dict]:
        """Validate only semantics the runtime evaluator can prove without guessing."""
        violations: list[dict] = []
        rules = list(
            HrDoubleTeacherRule.objects.filter(version_id=version).prefetch_related(
                "evidence_requirements"
            )
        )
        if not rules:
            return [{"violation": "RULE_VERSION_EMPTY", "description": "规则版本没有任何规则。"}]

        seen_codes = set()
        supported_operators = {">=", "<=", "==", "=", ">", "<"}
        combination_types = {RuleType.ANY_OF, RuleType.ONE_OF, RuleType.ALL_OF}
        for rule in rules:
            if rule.rule_code in seen_codes:
                violations.append(
                    {
                        "rule_code": rule.rule_code,
                        "violation": "RULE_CODE_DUPLICATE",
                        "description": "同一版本 rule_code 重复。",
                    }
                )
            seen_codes.add(rule.rule_code)
            requirements = list(rule.evidence_requirements.all())

            if rule.manual_review_required or rule.rule_type == RuleType.MANUAL_COMMITTEE:
                continue
            if not requirements:
                violations.append(
                    {
                        "rule_code": rule.rule_code,
                        "violation": "EVIDENCE_REQUIREMENT_MISSING",
                        "description": "非人工规则必须至少有一个证据要求。",
                    }
                )
                continue
            if rule.source_provider == "":
                violations.append(
                    {
                        "rule_code": rule.rule_code,
                        "violation": "SOURCE_PROVIDER_MISSING",
                        "description": "自动规则必须声明 source_provider。",
                    }
                )

            expected = rule.expected_value_json or {}
            if not isinstance(expected, dict):
                violations.append(
                    {
                        "rule_code": rule.rule_code,
                        "violation": "EXPECTED_VALUE_INVALID",
                        "description": "expected_value_json 必须是对象。",
                    }
                )
                continue

            if rule.rule_type == RuleType.BOOLEAN_FACT:
                if not isinstance(expected.get("value"), bool):
                    violations.append(
                        {
                            "rule_code": rule.rule_code,
                            "violation": "BOOLEAN_VALUE_REQUIRED",
                            "description": "BOOLEAN_FACT 需要布尔 value。",
                        }
                    )
            elif rule.rule_type == RuleType.COUNT:
                if cls._number(expected.get("min_count", expected.get("count", expected.get("value")))) is None:
                    violations.append(
                        {"rule_code": rule.rule_code, "violation": "COUNT_VALUE_REQUIRED", "description": "COUNT 需要数值阈值。"}
                    )
            elif rule.rule_type == RuleType.DURATION:
                if cls._number(expected.get("min_days", expected.get("days", expected.get("value")))) is None:
                    violations.append(
                        {"rule_code": rule.rule_code, "violation": "DURATION_VALUE_REQUIRED", "description": "DURATION 需要数值天数。"}
                    )
            elif rule.rule_type in {RuleType.LEVEL_AT_LEAST, RuleType.AWARD_LEVEL}:
                if cls._number(expected.get("min_rank", expected.get("rank"))) is None:
                    violations.append(
                        {
                            "rule_code": rule.rule_code,
                            "violation": "NORMALIZED_RANK_REQUIRED",
                            "description": "等级规则必须使用数值 min_rank/rank，禁止字符串等级猜序。",
                        }
                    )
            elif rule.rule_type in combination_types:
                if len(requirements) < 2:
                    violations.append(
                        {
                            "rule_code": rule.rule_code,
                            "violation": "COMBINATION_REQUIREMENTS_INSUFFICIENT",
                            "description": "ANY/ONE/ALL 组合规则至少需要两个独立证据要求。",
                        }
                    )
            elif rule.rule_type in {RuleType.ROLE_REQUIRED, RuleType.PROJECT_ROLE}:
                roles = expected.get("roles") or ([expected.get("role")] if expected.get("role") else [])
                if not isinstance(roles, list) or not [value for value in roles if value]:
                    violations.append(
                        {"rule_code": rule.rule_code, "violation": "ROLE_REQUIRED", "description": "角色规则需要 role/roles。"}
                    )
            elif rule.rule_type == RuleType.DATE_VALID:
                if cls._number(expected.get("max_age_days")) is None:
                    violations.append(
                        {"rule_code": rule.rule_code, "violation": "MAX_AGE_REQUIRED", "description": "DATE_VALID 需要 max_age_days。"}
                    )
            else:
                violations.append(
                    {
                        "rule_code": rule.rule_code,
                        "violation": "RULE_TYPE_NOT_AUTOMATABLE",
                        "description": f"规则类型 {rule.rule_type} 尚无可证明的 typed evaluator；请改为人工复核或受支持类型。",
                    }
                )

            if rule.operator not in supported_operators and rule.rule_type not in combination_types:
                violations.append(
                    {
                        "rule_code": rule.rule_code,
                        "violation": "OPERATOR_UNSUPPORTED",
                        "description": f"operator {rule.operator} 不受当前 typed evaluator 支持。",
                    }
                )

            for requirement in requirements:
                if requirement.min_level and cls._number(requirement.min_level) is None:
                    violations.append(
                        {
                            "rule_code": rule.rule_code,
                            "violation": "REQUIREMENT_LEVEL_NOT_NORMALIZED",
                            "description": "证据要求 min_level 必须是数值 rank。",
                        }
                    )
        return violations

    @staticmethod
    def diff_versions(
        from_version: HrDoubleTeacherRulePackVersion,
        to_version: HrDoubleTeacherRulePackVersion,
    ) -> dict:
        from_rules = {
            r.rule_code: RuleService._rule_payload(r)
            for r in HrDoubleTeacherRule.objects.filter(version_id=from_version)
        }
        to_rules = {
            r.rule_code: RuleService._rule_payload(r)
            for r in HrDoubleTeacherRule.objects.filter(version_id=to_version)
        }
        added = [code for code in to_rules if code not in from_rules]
        removed = [code for code in from_rules if code not in to_rules]
        modified = []
        for code in set(from_rules) & set(to_rules):
            if from_rules[code] != to_rules[code]:
                modified.append(
                    {"rule_code": code, "from": from_rules[code], "to": to_rules[code]}
                )
        return {
            "from_version": str(from_version.id),
            "to_version": str(to_version.id),
            "added_count": len(added),
            "removed_count": len(removed),
            "modified_count": len(modified),
            "added": added,
            "removed": removed,
            "modified": modified,
        }

    @classmethod
    @transaction.atomic
    def publish(cls, version: HrDoubleTeacherRulePackVersion) -> HrDoubleTeacherRulePackVersion:
        version = (
            HrDoubleTeacherRulePackVersion.objects.select_for_update()
            .select_related("rule_pack_id__parent_rule_pack_id")
            .filter(id=version.id)
            .first()
        )
        if version is None:
            raise RulePackError("RULE_VERSION_NOT_FOUND", "rule version not found")
        if version.status == RulePackVersionStatus.ACTIVE:
            cls.assert_version_integrity(version)
            return version
        if version.status not in {
            RulePackVersionStatus.DRAFT,
            RulePackVersionStatus.APPROVED,
        }:
            raise RulePackError(
                "RULE_VERSION_INVALID_STATE",
                f"cannot publish rule version from {version.status}",
            )
        if version.effective_to is not None and version.effective_to <= version.effective_from:
            raise RulePackError(
                "RULE_VERSION_EFFECTIVE_RANGE_INVALID",
                "effective_to must be later than effective_from",
            )

        violations = cls.validate_inheritance(version) + cls.validate_typed_rules(version)
        if violations:
            first = violations[0]
            raise RulePackError(
                first.get("violation", "RULE_VERSION_VALIDATION_FAILED"),
                f"cannot publish rule version: {len(violations)} violation(s); first: {first.get('description', first)}",
            )

        version.checksum = cls.compute_version_checksum(version)
        version.status = RulePackVersionStatus.ACTIVE
        version.published_at = timezone.now()
        version.save(update_fields=["checksum", "status", "published_at", "updated_at"])
        return version

    @classmethod
    @transaction.atomic
    def retire(cls, version: HrDoubleTeacherRulePackVersion) -> HrDoubleTeacherRulePackVersion:
        version = (
            HrDoubleTeacherRulePackVersion.objects.select_for_update()
            .filter(id=version.id)
            .first()
        )
        if version is None:
            raise RulePackError("RULE_VERSION_NOT_FOUND", "rule version not found")
        if version.status == RulePackVersionStatus.ACTIVE:
            cls.assert_version_integrity(version)
            version.status = RulePackVersionStatus.RETIRED
            version.save(update_fields=["status", "updated_at"])
        return version
