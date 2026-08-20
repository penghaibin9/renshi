"""Fail-closed typed precheck contracts."""

import uuid
from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_qualification.constants import (
    HardOrSoft,
    PrecheckResultType,
    ProviderStatus,
    RuleType,
)
from hr_qualification.providers.base import ProviderEvidenceResult
from hr_qualification.services.precheck_service import PrecheckService


class _Requirements:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


def _requirement(**overrides):
    values = {
        "id": uuid.uuid4(),
        "min_count": 1,
        "min_duration": None,
        "min_level": "",
        "verification_required": False,
        "document_required": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _rule(*, requirements, **overrides):
    values = {
        "rule_code": "R-1",
        "dimension_code": "TEST",
        "level": "DOUBLE_TEACHER_JUNIOR",
        "hard_or_soft": HardOrSoft.HARD,
        "source_provider": "HR03_EDUCATION",
        "manual_review_required": False,
        "rule_type": RuleType.BOOLEAN_FACT,
        "expected_value_json": {"value": True},
        "operator": ">=",
        "evidence_requirements": _Requirements(requirements),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _item(requirement, **overrides):
    values = {
        "requirement_id_id": requirement.id,
        "verification_status": "VERIFIED",
        "document_refs": ["file-1"],
        "quantitative_value": None,
        "snapshot_json": {},
        "role": "",
        "evidence_date": date(2026, 6, 1),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PrecheckHardeningTests(SimpleTestCase):
    def test_partial_provider_blocks_rule_instead_of_passing_available_subset(self):
        req = _requirement()
        rule = _rule(requirements=[req])
        result = PrecheckService._evaluate_rule(
            rule,
            [_item(req)],
            {"HR03_EDUCATION": ProviderEvidenceResult(status=ProviderStatus.PARTIAL)},
        )
        self.assertEqual(result.result, PrecheckResultType.SOURCE_UNAVAILABLE)

    def test_provider_error_is_rule_error(self):
        req = _requirement()
        rule = _rule(requirements=[req])
        result = PrecheckService._evaluate_rule(
            rule,
            [_item(req)],
            {"HR03_EDUCATION": ProviderEvidenceResult(status=ProviderStatus.ERROR)},
        )
        self.assertEqual(result.result, PrecheckResultType.RULE_ERROR)

    def test_missing_named_provider_result_fails_closed(self):
        req = _requirement()
        rule = _rule(requirements=[req])
        result = PrecheckService._evaluate_rule(rule, [_item(req)], {})
        self.assertEqual(result.result, PrecheckResultType.SOURCE_UNAVAILABLE)

    def test_document_and_verification_requirement_filters_are_real(self):
        req = _requirement(verification_required=True, document_required=True)
        rule = _rule(requirements=[req])
        result = PrecheckService._evaluate_rule(
            rule,
            [_item(req, verification_status="EXPIRED", document_refs=[])],
            {"HR03_EDUCATION": ProviderEvidenceResult(status=ProviderStatus.OK)},
        )
        self.assertEqual(result.result, PrecheckResultType.MISSING_EVIDENCE)

    def test_duration_rule_uses_quantitative_evidence(self):
        req = _requirement(min_count=2)
        rule = _rule(
            requirements=[req],
            rule_type=RuleType.DURATION,
            expected_value_json={"min_days": 180},
        )
        result = PrecheckService._evaluate_rule(
            rule,
            [
                _item(req, quantitative_value=100),
                _item(req, quantitative_value=90),
            ],
            {"HR03_EDUCATION": ProviderEvidenceResult(status=ProviderStatus.OK)},
        )
        self.assertEqual(result.result, PrecheckResultType.PASS)

    def test_level_rule_requires_normalized_rank_not_string_guessing(self):
        req = _requirement()
        rule = _rule(
            requirements=[req],
            rule_type=RuleType.LEVEL_AT_LEAST,
            expected_value_json={"min_level": "INTERMEDIATE"},
        )
        result = PrecheckService._evaluate_rule(
            rule,
            [_item(req, quantitative_value=4, snapshot_json={"level_rank": 4})],
            {"HR03_EDUCATION": ProviderEvidenceResult(status=ProviderStatus.OK)},
        )
        self.assertEqual(result.result, PrecheckResultType.RULE_ERROR)

    def test_any_of_does_not_degrade_into_all_of(self):
        first = _requirement()
        second = _requirement()
        rule = _rule(
            requirements=[first, second],
            rule_type=RuleType.ANY_OF,
            expected_value_json={"options": ["A", "B"]},
        )
        result = PrecheckService._evaluate_rule(
            rule,
            [_item(first)],
            {"HR03_EDUCATION": ProviderEvidenceResult(status=ProviderStatus.OK)},
        )
        self.assertEqual(result.result, PrecheckResultType.PASS)
