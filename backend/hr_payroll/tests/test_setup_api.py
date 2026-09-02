"""HR15 profile and period setup APIs."""

import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from unittest.mock import patch

from hr_payroll.models import PayrollPeriod, PayrollProfile
from hr_payroll.setup_api import create_period, create_profile, freeze_period_input, setup_options
from hr_staff.models import HrPerson, HrStaffMaster


class PayrollSetupApiTests(TestCase):
    tenant_id = 815

    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="hr15-setup", email="hr15-setup@example.invalid", password="test-password"
        )
        person = HrPerson.objects.create(tenant_id=self.tenant_id, legal_name="工资测试人员")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id, person_id=person, staff_no="PAY-001"
        )

    def post(self, path, body=None):
        request = self.factory.post(path, data=json.dumps(body or {}), content_type="application/json")
        request.user = self.user
        return request

    @patch("hr_payroll.setup_api.resolve_request_tenant", return_value=tenant_id)
    def test_profile_period_and_input_freeze_start_from_empty_state(self, _tenant):
        today = timezone.localdate()
        response = create_profile(self.post("/profiles/", {
            "staffId": str(self.staff.id), "payrollIdentityNo": "PAY-ID-001",
            "payGroupCode": "MONTHLY", "currencyCode": "CNY",
            "effectiveFrom": today.isoformat(),
        }))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(PayrollProfile.objects.filter(tenant_id=self.tenant_id, staff_id=self.staff.id).exists())

        response = create_period(self.post("/periods/", {
            "periodCode": "2026-09", "startDate": "2026-09-01", "endDate": "2026-09-30",
        }))
        self.assertEqual(response.status_code, 201)
        period = PayrollPeriod.objects.get(tenant_id=self.tenant_id)
        response = freeze_period_input(self.post(f"/periods/{period.id}/freeze-input/"), period.id)
        self.assertEqual(response.status_code, 200)
        period.refresh_from_db()
        self.assertEqual(period.status, PayrollPeriod.Status.INPUT_FROZEN)

    @patch("hr_payroll.setup_api.resolve_request_tenant", return_value=tenant_id)
    def test_overlapping_period_is_rejected(self, _tenant):
        PayrollPeriod.objects.create(
            tenant_id=self.tenant_id, period_code="2026-09", start_date="2026-09-01", end_date="2026-09-30"
        )
        response = create_period(self.post("/periods/", {
            "periodCode": "OVERLAP", "startDate": "2026-09-15", "endDate": "2026-10-15",
        }))
        self.assertEqual(response.status_code, 409)

    @patch("hr_payroll.setup_api.resolve_request_tenant", return_value=tenant_id)
    def test_setup_options_only_include_current_tenant(self, _tenant):
        PayrollPeriod.objects.create(
            tenant_id=self.tenant_id, period_code="LOCAL", start_date="2026-10-01", end_date="2026-10-31"
        )
        PayrollPeriod.objects.create(
            tenant_id=816, period_code="FOREIGN", start_date="2026-10-01", end_date="2026-10-31"
        )
        request = self.factory.get("/setup-options/")
        request.user = self.user
        response = setup_options(request)
        codes = [item["label"] for item in json.loads(response.content)["data"]["periods"]]
        self.assertTrue(any("LOCAL" in label for label in codes))
        self.assertFalse(any("FOREIGN" in label for label in codes))
