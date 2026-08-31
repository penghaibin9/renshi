"""
hr_recruitment/services/rule_engine.py

资格自动预检（《04_HR04_总册》§3.3/§11.5）。

硬规则：
- 系统只能输出建议：PASS / FAIL / DATA_MISSING / NEEDS_MANUAL_REVIEW / NOT_APPLICABLE；
- 不得默认作出最终"不合格"结论；
- 最终资格结论必须记录人工审核人和依据（QualificationDecision）。
"""

from __future__ import annotations

from dataclasses import dataclass

from hr_recruitment.constants import RuleSeverity, RuleSystemResult


@dataclass(frozen=True)
class RuleCheckResult:
    rule_code: str
    label: str
    severity: str
    system_result: str
    evidence: str = ""
    note: str = ""


class RuleEngine:
    """
    规则引擎（结构化规则 → 预检建议）。

    expected_value_json 支持的 operator：
      eq / ne / gte / lte / in / contains  / is_empty / not_empty
    V1 最小实现：文本/数值比较 + 缺失检测。
    """

    def evaluate(self, rule, candidate_data: dict) -> RuleCheckResult:
        """对单个规则做预检。candidate_data 为申请表单/结构化资料。"""
        rule_code = rule.rule_code
        operator = rule.operator or "eq"
        expected = rule.expected_value_json or {}
        field = expected.get("field")
        expected_value = expected.get("value")

        if not field:
            return RuleCheckResult(
                rule_code=rule_code,
                label=rule.label,
                severity=rule.severity,
                system_result=RuleSystemResult.NOT_APPLICABLE,
                note="规则未配置校验字段",
            )

        if field not in candidate_data or candidate_data.get(field) in (None, "", []):
            return RuleCheckResult(
                rule_code=rule_code,
                label=rule.label,
                severity=rule.severity,
                system_result=RuleSystemResult.DATA_MISSING,
                note=f"缺少字段 {field}",
            )

        actual = candidate_data.get(field)
        result = self._compare(operator, actual, expected_value)
        # HARD 规则 FAIL 只给 FAIL 建议；最终结论仍需人工审核
        return RuleCheckResult(
            rule_code=rule_code,
            label=rule.label,
            severity=rule.severity,
            system_result=result,
            evidence=f"{field}={actual}",
        )

    def _compare(self, operator: str, actual, expected) -> str:
        try:
            if operator == "eq":
                ok = actual == expected
            elif operator == "ne":
                ok = actual != expected
            elif operator in ("gte", "lte"):
                ok = (float(actual) >= float(expected)) if operator == "gte" else (float(actual) <= float(expected))
            elif operator == "in":
                ok = actual in (expected or [])
            elif operator == "contains":
                ok = str(expected) in str(actual)
            elif operator == "is_empty":
                ok = not actual
            elif operator == "not_empty":
                ok = bool(actual)
            else:
                ok = True
        except (TypeError, ValueError):
            return RuleSystemResult.NEEDS_MANUAL_REVIEW
        return RuleSystemResult.PASS if ok else RuleSystemResult.FAIL

    def evaluate_all(self, rules, candidate_data: dict) -> list[RuleCheckResult]:
        """全量预检（按 sequence 排序）。返回建议列表，不产出最终结论。"""
        results = []
        for rule in rules.order_by("sequence"):
            results.append(self.evaluate(rule, candidate_data))
        return results

    def overall_suggestion(self, results: list[RuleCheckResult]) -> str:
        """整体建议：任一 HARD FAIL → NEEDS_MANUAL_REVIEW（不直接终审）。"""
        hard_fail = [r for r in results if r.severity == RuleSeverity.HARD and r.system_result == RuleSystemResult.FAIL]
        if hard_fail:
            return RuleSystemResult.NEEDS_MANUAL_REVIEW
        missing = [r for r in results if r.system_result == RuleSystemResult.DATA_MISSING]
        if missing:
            return RuleSystemResult.DATA_MISSING
        if all(r.system_result == RuleSystemResult.PASS for r in results):
            return RuleSystemResult.PASS
        return RuleSystemResult.NEEDS_MANUAL_REVIEW
