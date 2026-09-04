import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import retirement_api
from hr_exit.services.retirement_policy_service import _policy_retirement_age_months


class ChinaRetirementCohortFormulaTests(SimpleTestCase):
    @staticmethod
    def policy(base, start, step, maximum):
        return SimpleNamespace(
            retirement_age_months=base,
            transition_birth_start=start,
            delay_step_birth_months=step,
            max_retirement_age_months=maximum,
        )

    def test_male_and_original_55_age_cohorts_delay_one_month_per_four_birth_months(self):
        policy = self.policy(720, date(1965, 1, 1), 4, 756)
        self.assertEqual(_policy_retirement_age_months(policy, date(1964, 12, 31)), 720)
        self.assertEqual(_policy_retirement_age_months(policy, date(1965, 1, 1)), 721)
        self.assertEqual(_policy_retirement_age_months(policy, date(1965, 4, 30)), 721)
        self.assertEqual(_policy_retirement_age_months(policy, date(1965, 5, 1)), 722)
        self.assertEqual(_policy_retirement_age_months(policy, date(2100, 1, 1)), 756)

    def test_original_50_age_female_cohorts_delay_one_month_per_two_birth_months(self):
        policy = self.policy(600, date(1975, 1, 1), 2, 660)
        self.assertEqual(_policy_retirement_age_months(policy, date(1975, 1, 1)), 601)
        self.assertEqual(_policy_retirement_age_months(policy, date(1975, 2, 28)), 601)
        self.assertEqual(_policy_retirement_age_months(policy, date(1975, 3, 1)), 602)


class RetirementPolicyApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.person_id = uuid.uuid4()
        self.relationship_id = uuid.uuid4()

    def _post(self, path, payload):
        request = self.factory.post(
            path, data=json.dumps(payload), content_type="application/json"
        )
        request.user = SimpleNamespace(id=9)
        return request

    @patch("hr_exit.retirement_api.RetirementPolicyService")
    @patch("hr_exit.retirement_api.resolve_request_tenant", return_value=77)
    def test_policy_api_accepts_chinese_gradual_retirement_parameters(
        self, _tenant, service_cls
    ):
        service_cls.return_value.create_draft.return_value = SimpleNamespace(
            id=uuid.uuid4(),
            policy_code="CN-DELAY-MALE",
            version_no=1,
            status="DRAFT",
            content_hash="a" * 64,
            retirement_type="STATUTORY",
            gender_code="M",
            staff_category_code="",
            relationship_type="",
            special_condition_code="",
            retirement_age_months=720,
            transition_birth_start=date(1965, 1, 1),
            delay_step_birth_months=4,
            max_retirement_age_months=756,
            minimum_service_months=0,
            effective_from=date(2025, 1, 1),
            effective_to=None,
            priority=100,
            rationale="全国人大常委会决定及国务院办法",
        )
        request = self._post(
            "/api/v1/hr/exit/retirement-policies/",
            {
                "policyCode": "CN-DELAY-MALE",
                "retirementType": "STATUTORY",
                "genderCode": "M",
                "retirementAgeMonths": 720,
                "transitionBirthStart": "1965-01-01",
                "delayStepBirthMonths": 4,
                "maxRetirementAgeMonths": 756,
                "effectiveFrom": "2025-01-01",
                "priority": 100,
                "rationale": "全国人大常委会决定及国务院办法",
            },
        )

        response = retirement_api.create_retirement_policy(request)

        self.assertEqual(response.status_code, 201)
        kwargs = service_cls.return_value.create_draft.call_args.kwargs
        self.assertEqual(kwargs["transition_birth_start"], date(1965, 1, 1))
        self.assertEqual(kwargs["delay_step_birth_months"], 4)
        self.assertEqual(kwargs["max_retirement_age_months"], 756)

    @patch("hr_exit.retirement_api.RetirementPrecheckService")
    @patch("hr_exit.retirement_api.resolve_request_tenant", return_value=77)
    def test_precheck_uses_authoritative_service_and_returns_explanation(self, _tenant, service_cls):
        precheck = SimpleNamespace(
            id=uuid.uuid4(),
            person_id=self.person_id,
            employment_relationship_id=self.relationship_id,
            as_of=date(2026, 8, 30),
            decision="ELIGIBLE",
            retirement_type="STATUTORY",
            statutory_date=date(2026, 2, 28),
            matched_policy_id=uuid.uuid4(),
            matched_policy_version=3,
            explanation_json={"reasonCodes": []},
        )
        service_cls.return_value.evaluate.return_value = SimpleNamespace(
            precheck=precheck, created=True
        )
        request = self._post(
            "/api/v1/hr/exit/retirement-prechecks/",
            {
                "personId": str(self.person_id),
                "employmentRelationshipId": str(self.relationship_id),
                "asOf": "2026-08-30",
                "idempotencyKey": "precheck:1",
                "specialConditionCodes": [],
            },
        )

        response = retirement_api.run_retirement_precheck(request)

        self.assertEqual(response.status_code, 201)
        self.assertIn(b'"decision": "ELIGIBLE"', response.content)
        service_cls.return_value.evaluate.assert_called_once()

    @patch("hr_exit.retirement_api.resolve_request_tenant", return_value=77)
    def test_precheck_rejects_client_supplied_non_uuid_source(self, _tenant):
        request = self._post(
            "/api/v1/hr/exit/retirement-prechecks/",
            {
                "personId": "not-a-uuid",
                "employmentRelationshipId": str(self.relationship_id),
                "asOf": "2026-08-30",
            },
        )
        response = retirement_api.run_retirement_precheck(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"RETIREMENT_PRECHECK_ID_INVALID", response.content)
