import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from hr_exit import retirement_api


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88


class RetirementApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.exit_fact_id = uuid.uuid4()
        self.retirement_fact_id = uuid.uuid4()
        self.person_id = uuid.uuid4()

    def _fact(self, *, pension_status="NOT_STARTED"):
        return SimpleNamespace(
            id=self.retirement_fact_id,
            fact_no="RET-2026-001",
            person_id=self.person_id,
            exit_fact_id=self.exit_fact_id,
            retirement_type="STATUTORY",
            statutory_date=date(2026, 9, 1),
            effective_date=date(2026, 9, 1),
            pension_processing_status=pension_status,
            status="EFFECTIVE",
        )

    @patch("hr_exit.retirement_api.RetirementFactService")
    @patch("hr_exit.retirement_api.resolve_request_tenant", return_value=77)
    def test_finalize_requires_effect_permission_and_freezes_effective_date(
        self, tenant_resolver, service_cls
    ):
        fact = self._fact()
        service_cls.return_value.finalize.return_value = SimpleNamespace(
            fact=fact, created=True
        )
        request = self.factory.post(
            f"/api/v1/hr/exit/exit-facts/{self.exit_fact_id}/retirement/",
            data=json.dumps(
                {
                    "factNo": "RET-2026-001",
                    "retirementType": "STATUTORY",
                    "statutoryDate": "2026-09-01",
                    "effectiveDate": "2030-01-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = retirement_api.finalize_retirement(request, self.exit_fact_id)

        self.assertEqual(response.status_code, 201)
        tenant_resolver.assert_called_once_with(
            request, required_permission=retirement_api.EFFECT_PERMISSION
        )
        kwargs = service_cls.return_value.finalize.call_args.kwargs
        self.assertNotIn("effective_date", kwargs)
        self.assertEqual(kwargs["statutory_date"], date(2026, 9, 1))
        self.assertIn(b'"effectiveDate": "2026-09-01"', response.content)

    @patch("hr_exit.retirement_api.RetirementFactService")
    @patch("hr_exit.retirement_api.resolve_request_tenant", return_value=77)
    def test_pension_progress_uses_manage_permission(
        self, tenant_resolver, service_cls
    ):
        service_cls.return_value.set_pension_status.return_value = self._fact(
            pension_status="IN_PROGRESS"
        )
        request = self.factory.post(
            f"/api/v1/hr/exit/retirement-facts/{self.retirement_fact_id}/pension-status/",
            data=json.dumps({"status": "IN_PROGRESS"}),
            content_type="application/json",
        )
        request.user = UserStub()

        response = retirement_api.set_pension_status(request, self.retirement_fact_id)

        self.assertEqual(response.status_code, 200)
        tenant_resolver.assert_called_once_with(
            request, required_permission=retirement_api.MANAGE_PERMISSION
        )
        service_cls.return_value.set_pension_status.assert_called_once_with(
            self.retirement_fact_id, status="IN_PROGRESS"
        )

    @patch("hr_exit.retirement_api.resolve_request_tenant", return_value=77)
    def test_invalid_statutory_date_is_rejected(self, _tenant):
        request = self.factory.post(
            f"/api/v1/hr/exit/exit-facts/{self.exit_fact_id}/retirement/",
            data=json.dumps(
                {
                    "factNo": "RET-2026-001",
                    "retirementType": "STATUTORY",
                    "statutoryDate": "2026-99-99",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = retirement_api.finalize_retirement(request, self.exit_fact_id)

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"RETIREMENT_STATUTORY_DATE_INVALID", response.content)
