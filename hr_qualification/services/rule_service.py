"""
hr_qualification/services/rule_service.py —— 双师规则服务（总册 §47/§113/§48）。

- 规则四层继承校验（学校不得弱化国家 HARD Rule）
- Rule Diff（两版本比较）
- Publish（ACTIVE 后 immutable）
"""

from __future__ import annotations

import hashlib
import json

from django.db import transaction

from hr_qualification.constants import HardOrSoft, RulePackVersionStatus
from hr_qualification.models import (
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)


class RulePackError(Exception):
    pass


class RuleService:
    """双师规则服务。"""

    @staticmethod
    def validate_inheritance(version: HrDoubleTeacherRulePackVersion) -> list[dict]:
        """校验学校规则不低于父级（国家/省级）HARD Rule。

        返回问题列表；空列表 = 通过。
        """
        violations: list[dict] = []

        # 找到父 RulePack → 找到其 ACTIVE Version
        pack = version.rule_pack_id
        if not pack.parent_rule_pack_id:
            return violations  # 国家级，无需校验

        try:
            parent_version = HrDoubleTeacherRulePackVersion.objects.filter(
                rule_pack_id=pack.parent_rule_pack_id,
                status=RulePackVersionStatus.ACTIVE,
            ).latest("version_no")
        except HrDoubleTeacherRulePackVersion.DoesNotExist:
            return violations

        # 对比每条 HARD Rule
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
                violations.append({
                    "rule_code": code,
                    "dimension": parent_rule.dimension_code,
                    "level": parent_rule.level,
                    "violation": "HARD_RULE_REMOVED",
                    "description": f"父级 HARD Rule {code} 被删除。",
                })
                continue

            if child_rule.rule_type != parent_rule.rule_type:
                violations.append({
                    "rule_code": code,
                    "violation": "RULE_TYPE_CHANGED",
                    "description": f"规则类型从 {parent_rule.rule_type} 变为 {child_rule.rule_type}。",
                })

            if child_rule.hard_or_soft == HardOrSoft.SOFT:
                violations.append({
                    "rule_code": code,
                    "violation": "RULE_WEAKER_THAN_PARENT",
                    "description": f"父级 HARD Rule {code} 在本级被降为 SOFT。",
                })

        return violations

    @staticmethod
    def diff_versions(
        from_version: HrDoubleTeacherRulePackVersion,
        to_version: HrDoubleTeacherRulePackVersion,
    ) -> dict:
        """两个规则版本 Diff。"""
        from_rules = {
            r.rule_code: {
                "rule_type": r.rule_type,
                "dimension_code": r.dimension_code,
                "level": r.level,
                "expected_value": r.expected_value_json,
                "hard_or_soft": r.hard_or_soft,
                "source_provider": r.source_provider,
            }
            for r in HrDoubleTeacherRule.objects.filter(version_id=from_version)
        }
        to_rules = {
            r.rule_code: {
                "rule_type": r.rule_type,
                "dimension_code": r.dimension_code,
                "level": r.level,
                "expected_value": r.expected_value_json,
                "hard_or_soft": r.hard_or_soft,
                "source_provider": r.source_provider,
            }
            for r in HrDoubleTeacherRule.objects.filter(version_id=to_version)
        }

        added = [code for code in to_rules if code not in from_rules]
        removed = [code for code in from_rules if code not in to_rules]
        modified = []
        for code in set(from_rules) & set(to_rules):
            if from_rules[code] != to_rules[code]:
                modified.append({
                    "rule_code": code,
                    "from": from_rules[code],
                    "to": to_rules[code],
                })

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

    @staticmethod
    def publish(version: HrDoubleTeacherRulePackVersion) -> HrDoubleTeacherRulePackVersion:
        """发布规则版本（ACTIVE 后 immutable）。

        发布前自动校验继承关系。
        """
        violations = RuleService.validate_inheritance(version)
        if violations:
            raise RulePackError(
                f"Cannot publish rule version: {len(violations)} inheritance violation(s). "
                f"First: {violations[0]['violation']}"
            )

        with transaction.atomic():
            version.status = RulePackVersionStatus.ACTIVE
            # 计算 checksum
            rules = list(
                HrDoubleTeacherRule.objects
                .filter(version_id=version)
                .order_by("sequence")
                .values_list("rule_code", "rule_type", "expected_value_json")
            )
            version.checksum = hashlib.sha256(
                json.dumps(rules, sort_keys=True, default=str).encode()
            ).hexdigest()
            version.save()
        return version

    @staticmethod
    def retire(version: HrDoubleTeacherRulePackVersion) -> HrDoubleTeacherRulePackVersion:
        if version.status == RulePackVersionStatus.ACTIVE:
            version.status = RulePackVersionStatus.RETIRED
            version.save()
        return version
