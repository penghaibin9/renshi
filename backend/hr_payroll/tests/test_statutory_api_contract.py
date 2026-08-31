import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import RequestFactory, SimpleTestCase

from hr_payroll import api
from hr_payroll.authority_registry import PERM_STATUTORY_MANAGE, PERM_STATUTORY_VIEW
from hr_payroll.services.statutory_contribution_service import (
    StatutoryContributionService,
    evidence_hash,
)
from hr_payroll.statutory_models import StatutoryContributionRuleVersion


class _User:
    is_authenticated = True
    is_superuser = False
    id = 1515

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, permission):
        return permission in self.permissions


class StatutoryContributionApiContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.payload = {
            "ruleCode": "BJ-HOUSING-FUND",
            "versionNo": 1,
            "contributionGroup": "HOUSING_FUND",
            "contributionCode": "HOUSING_FUND",
            "name": "住房公积金",
            "jurisdictionCode": "CN-11",
            "baseVariableKey": "housingFundBase",
            "baseFloor": "2500.00",
            "baseCeiling": "35000.00",
            "employeeRate": "0.12",
            "employerRate": "0.12",
            "employeeItemCode": "HOUSING_FUND_EMPLOYEE",
            "employerItemCode": "HOUSING_FUND_EMPLOYER",
            "effectiveFrom": "2026-01-01",
            "policyEvidence": {"documentNo": "京房公积金发〔2026〕1号"},
        }

    def _post(self, permissions):
        request = self.factory.post(
            "/api/v1/hr/payroll/statutory-rules/",
            data=json.dumps(self.payload),
            content_type="application/json",
        )
        request.user = _User(permissions)
        return request

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    def test_view_permission_cannot_write_statutory_rule(self, _allowed, _tenant):
        with patch("hr_payroll.api.StatutoryContributionRuleService") as service:
            response = api.statutory_rules(self._post({PERM_STATUTORY_VIEW}))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"]["code"], "PERMISSION_DENIED")
        service.assert_not_called()

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value=[77])
    @patch("hr_payroll.api.StatutoryContributionRuleService")
    def test_manager_creates_versioned_rule_contract(self, service_cls, _allowed, _tenant):
        service_cls.return_value.create_draft.return_value = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000001515"),
            rule_code="BJ-HOUSING-FUND",
            version_no=1,
            contribution_group="HOUSING_FUND",
            contribution_code="HOUSING_FUND",
            name="住房公积金",
            jurisdiction_code="CN-11",
            base_variable_key="housingFundBase",
            base_floor=Decimal("2500.00"),
            base_ceiling=Decimal("35000.00"),
            employee_rate=Decimal("0.120000"),
            employer_rate=Decimal("0.120000"),
            employee_item_code="HOUSING_FUND_EMPLOYEE",
            employer_item_code="HOUSING_FUND_EMPLOYER",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            policy_evidence_json={"documentNo": "京房公积金发〔2026〕1号"},
            content_hash="",
            status="DRAFT",
        )
        response = api.statutory_rules(self._post({PERM_STATUTORY_MANAGE}))
        body = json.loads(response.content)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(body["schemaVersion"], "hr15.statutory-rule.1")
        self.assertEqual(body["data"]["baseCeiling"], "35000.00")
        self.assertEqual(body["data"]["policyEvidence"]["documentNo"], "京房公积金发〔2026〕1号")
        service_cls.assert_called_once_with(77, actor_user_id=1515, correlation_id="")

    def test_non_post_publish_is_rejected_before_authority_lookup(self):
        request = self.factory.get("/api/v1/hr/payroll/statutory-rules/x/publish/")
        request.user = _User({PERM_STATUTORY_MANAGE})
        with patch("hr_payroll.api.StatutoryContributionRuleService") as service:
            response = api.publish_statutory_rule(
                request, UUID("00000000-0000-0000-0000-000000001515")
            )
        self.assertEqual(response.status_code, 405)
        service.assert_not_called()

    def test_decimal_calculation_clamps_base_and_hash_is_deterministic(self):
        rule = StatutoryContributionRuleVersion(
            tenant_id=77,
            contribution_group="SOCIAL_INSURANCE",
            contribution_code="BASIC_PENSION",
            base_variable_key="socialInsuranceBase",
            base_floor=Decimal("6000.00"),
            base_ceiling=Decimal("30000.00"),
            employee_rate=Decimal("0.080000"),
            employer_rate=Decimal("0.160000"),
        )
        result = StatutoryContributionService.calculate(
            rule, {"socialInsuranceBase": "5000.00"}
        )
        self.assertEqual(result.contribution_base, Decimal("6000.00"))
        self.assertEqual(result.employee_amount, Decimal("480.00"))
        self.assertEqual(result.employer_amount, Decimal("960.00"))
        self.assertEqual(evidence_hash({"b": 2, "a": 1}), evidence_hash({"a": 1, "b": 2}))
