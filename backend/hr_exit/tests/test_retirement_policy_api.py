import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import retirement_api


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
