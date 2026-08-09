"""
hr_qualification/services/precheck_service.py —— 系统预检引擎（总册 §61-63/§116）。

- 基于 Frozen RuleVersion 的自动预检
- 输出：PASS / FAIL_HARD_RULE / MISSING_EVIDENCE / MANUAL_REVIEW_REQUIRED / SOURCE_UNAVAILABLE / RULE_ERROR
- SOURCE_UNAVAILABLE ≠ FAIL（关键硬门）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from hr_qualification.constants import (
    HardOrSoft,
    PrecheckResultType,
    ProviderStatus as PS,
)
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherRule,
)
from hr_qualification.providers.base import ProviderEvidenceResult


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
    overall: PrecheckResultType  # PASS / FAIL_HARD_RULE / ...
    items: list[PrecheckItem] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    manual_review: int = 0
    missing: int = 0
    source_unavailable: int = 0


class PrecheckService:
    """系统预检引擎。"""

    @staticmethod
    def precheck(
        application: HrDoubleTeacherApplication,
        evidence_package: HrDoubleTeacherEvidencePackage,
        provider_results: dict[str, ProviderEvidenceResult] | None = None,
    ) -> PrecheckResult:
        """对申报进行规则预检。"""
        # 加载批次绑定的规则
        rules = list(
            HrDoubleTeacherRule.objects.filter(
                version_id=application.batch_id.rule_pack_version_id,
                level=application.target_level,
            ).order_by("sequence")
        )

        evidence_items = list(
            HrDoubleTeacherEvidenceItem.objects.filter(package_id=evidence_package)
        )

        items: list[PrecheckItem] = []
        passed = failed = manual = missing = src_unavailable = 0

        for rule in rules:
            item = PrecheckService._evaluate_rule(
                rule, evidence_items, provider_results
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

        # 判定整体结果
        overall = PrecheckResultType.PASS
        if failed > 0:
            overall = PrecheckResultType.FAIL_HARD_RULE
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
        )

    @staticmethod
    def _evaluate_rule(
        rule: HrDoubleTeacherRule,
        evidence_items: list[HrDoubleTeacherEvidenceItem],
        provider_results: dict[str, ProviderEvidenceResult] | None = None,
    ) -> PrecheckItem:
        """单条规则评估。"""
        provider_results = provider_results or {}

        # 检查 Provider 是否不可用
        source = rule.source_provider
        if source and source in provider_results:
            if provider_results[source].status == PS.UNAVAILABLE:
                return PrecheckItem(
                    rule_code=rule.rule_code,
                    dimension_code=rule.dimension_code,
                    level=rule.level,
                    hard_or_soft=rule.hard_or_soft,
                    result=PrecheckResultType.SOURCE_UNAVAILABLE,
                    detail=f"Provider {source} is UNAVAILABLE",
                )

        # 需要人工评审
        if rule.manual_review_required:
            return PrecheckItem(
                rule_code=rule.rule_code,
                dimension_code=rule.dimension_code,
                level=rule.level,
                hard_or_soft=rule.hard_or_soft,
                result=PrecheckResultType.MANUAL_REVIEW_REQUIRED,
                detail="Manual review required by rule",
            )

        # 匹配证据
        related = [
            e for e in evidence_items
            if e.requirement_id
            and str(e.requirement_id.rule_id_id) == str(rule.id)
        ]
        evidence_count = len(related)

        if rule.hard_or_soft == HardOrSoft.HARD and evidence_count == 0:
            return PrecheckItem(
                rule_code=rule.rule_code,
                dimension_code=rule.dimension_code,
                level=rule.level,
                hard_or_soft=rule.hard_or_soft,
                result=PrecheckResultType.MISSING_EVIDENCE,
                evidence_count=0,
                detail=f"No evidence found for HARD rule {rule.rule_code}",
            )

        return PrecheckItem(
            rule_code=rule.rule_code,
            dimension_code=rule.dimension_code,
            level=rule.level,
            hard_or_soft=rule.hard_or_soft,
            result=PrecheckResultType.PASS,
            evidence_count=evidence_count,
            detail=f"Evidence count: {evidence_count}",
        )
