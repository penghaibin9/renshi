import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import RequestFactory, SimpleTestCase

from hr_payroll import api
from hr_payroll.authority_registry import PERM_BENEFIT_MANAGE, PERM_BENEFIT_VIEW


class _User:
    is_authenticated = True
    is_superuser = False
    id = 1515

    def __init__(self, permissions=()):
        self.permissions = set(permissions)

    def has_perm(self, permission):
        return permission in self.permissions


class BenefitApiContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.payload = {
            "planCode": "JT-TRAFFIC",
            "versionNo": 1,
            "name": "交通补贴",
            "benefitType": "TRANSPORT_ALLOWANCE",
            "providerName": "学校",
            "fixedAmount": "300.00",
            "employerRate": "0",
            "employeeRate": "0",
            "effectiveFrom": "2026-01-01",
            "ruleSnapshot": {"scope": "active_staff"},
        }

    def _post(self, path, payload, permissions):
        request = self.factory.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = _User(permissions)
        return request

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    def test_view_permission_cannot_create_plan(self, _allowed, _tenant):
        request = self._post(
            "/api/v1/hr/payroll/benefit-plans/",
            self.payload,
            {PERM_BENEFIT_VIEW},
        )

        with patch("hr_payroll.api.BenefitPensionAuthorityService") as service:
            response = api.benefit_plans(request)

        self.assertEqual(response.status_code, 403)
        service.assert_not_called()

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    @patch("hr_payroll.api.BenefitPensionAuthorityService")
    def test_manager_creates_versioned_benefit_plan(
        self, service_cls, _allowed, _tenant
    ):
        service_cls.return_value.create_benefit_plan.return_value = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000001515"),
            plan_code="JT-TRAFFIC",
            version_no=1,
            name="交通补贴",
            benefit_type="TRANSPORT_ALLOWANCE",
            provider_name="学校",
            currency_code="CNY",
            employer_rate=Decimal("0"),
            employee_rate=Decimal("0"),
            fixed_amount=Decimal("300.00"),
            effective_from=date(2026, 1, 1),
            effective_to=None,
            rule_snapshot_json={"scope": "active_staff"},
            content_hash="",
            status="DRAFT",
        )
        request = self._post(
            "/api/v1/hr/payroll/benefit-plans/",
            self.payload,
            {PERM_BENEFIT_MANAGE},
        )

        response = api.benefit_plans(request)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(body["schemaVersion"], "hr15.benefit-plan.1")
        self.assertEqual(body["data"]["fixedAmount"], "300.00")
        service_cls.assert_called_once_with(
            77, actor_user_id=1515, correlation_id=""
        )

    @patch("hr_payroll.api.resolve_tenant_from_request", return_value=77)
    @patch("hr_payroll.api.get_allowed_company_ids", return_value={77})
    @patch("hr_payroll.api.BenefitPensionAuthorityService")
    def test_manager_enrolls_current_tenant_staff(
        self, service_cls, _allowed, _tenant
    ):
        plan_id = UUID("00000000-0000-0000-0000-000000000015")
        staff_id = UUID("00000000-0000-0000-0000-000000000003")
        service_cls.return_value.enroll_benefit.return_value = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000001516"),
            enrollment_no="FL-2026-0001",
            benefit_plan_id=plan_id,
            staff_id=staff_id,
            effective_from=date(2026, 1, 1),
            effective_to=None,
            employer_amount=Decimal("300.00"),
            employee_amount=Decimal("0.00"),
            snapshot_json={},
            supersedes_enrollment_id=None,
        )
        request = self._post(
            "/api/v1/hr/payroll/benefit-enrollments/",
            {
                "enrollmentNo": "FL-2026-0001",
                "benefitPlanId": str(plan_id),
                "staffId": str(staff_id),
                "effectiveFrom": "2026-01-01",
                "employerAmount": "300.00",
            },
            {PERM_BENEFIT_MANAGE},
        )

        response = api.benefit_enrollments(request)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(body["data"]["enrollmentNo"], "FL-2026-0001")
        self.assertEqual(body["data"]["employerAmount"], "300.00")

    def test_non_post_publish_is_rejected_before_authority_lookup(self):
        request = self.factory.get(
            "/api/v1/hr/payroll/benefit-plans/x/publish/"
        )
        request.user = _User({PERM_BENEFIT_MANAGE})

        with patch("hr_payroll.api.BenefitPensionAuthorityService") as service:
            response = api.publish_benefit_plan(
                request, UUID("00000000-0000-0000-0000-000000001515")
            )

        self.assertEqual(response.status_code, 405)
        service.assert_not_called()
