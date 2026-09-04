"""HR14 setup APIs cover policy and empty-state choices."""

import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from unittest.mock import patch

from hr_appointment.models import AppointmentPolicyVersion
from hr_appointment.setup_api import create_policy, setup_options


class AppointmentSetupApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="hr14-setup", email="hr14-setup@example.invalid", password="test-password"
        )

    @patch("hr_appointment.setup_api.resolve_request_tenant", return_value=714)
    def test_policy_version_can_be_created_from_empty_state(self, _tenant):
        request = self.factory.post(
            "/api/v1/hr/appointments/policies/",
            data=json.dumps({
                "policyCode": "APPOINT_2026", "name": "2026 岗位聘任办法",
                "effectiveFrom": timezone.localdate().isoformat(),
                "positionCategory": "PROFESSIONAL_TECHNICAL", "levelCode": "PT-7",
            }),
            content_type="application/json",
        )
        request.user = self.user
        response = create_policy(request)
        self.assertEqual(response.status_code, 201)
        policy = AppointmentPolicyVersion.objects.get(tenant_id=714)
        self.assertEqual(policy.status, "PUBLISHED")
        self.assertEqual(policy.version_no, 1)

    @patch("hr_appointment.setup_api.PositionSelector.list_positions", return_value={"total": 0, "items": []})
    @patch("hr_appointment.setup_api.resolve_request_tenant", return_value=714)
    def test_setup_options_are_tenant_scoped(self, _tenant, _positions):
        AppointmentPolicyVersion.objects.create(
            tenant_id=714, policy_code="LOCAL", name="本校制度", version_no=1,
            status="PUBLISHED", effective_from=timezone.localdate(),
        )
        AppointmentPolicyVersion.objects.create(
            tenant_id=715, policy_code="FOREIGN", name="外校制度", version_no=1,
            status="PUBLISHED", effective_from=timezone.localdate(),
        )
        request = self.factory.get("/api/v1/hr/appointments/setup-options/")
        request.user = self.user
        response = setup_options(request)
        self.assertEqual(response.status_code, 200)
        labels = [item["label"] for item in json.loads(response.content)["data"]["policies"]]
        self.assertTrue(any("本校制度" in label for label in labels))
        self.assertFalse(any("外校制度" in label for label in labels))

