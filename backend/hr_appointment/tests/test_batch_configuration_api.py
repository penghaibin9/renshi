import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from hr_appointment import batch_configuration_api
from hr_appointment.models import AppointmentBatch
from hr_appointment.services.batch_configuration_service import (
    AppointmentBatchConfigurationError,
)


class UserStub:
    is_authenticated = True
    is_superuser = False
    id = 88

    def has_perm(self, code):
        return code == batch_configuration_api.MANAGE_PERMISSION


class AppointmentBatchConfigurationApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.batch_id = uuid.uuid4()
        self.policy_id = uuid.uuid4()

    @patch(
        "hr_appointment.batch_configuration_api.resolve_request_tenant",
        return_value=77,
    )
    @patch("hr_appointment.batch_configuration_api.AppointmentBatchConfigurationService")
    def test_patch_parses_expected_version_and_returns_etag(self, service_cls, resolve_tenant):
        now = timezone.now().replace(microsecond=0)
        batch = SimpleNamespace(
            id=self.batch_id,
            batch_no="B-PATCH-API",
            name="已配置批次",
            business_type="COMPETITIVE_APPOINTMENT",
            policy_version_id=self.policy_id,
            target_categories_json=["PROFESSIONAL_TECHNICAL"],
            target_levels_json=["PT-7"],
            application_from=now,
            application_to=now + timedelta(days=5),
            publicity_from=now + timedelta(days=10),
            publicity_to=now + timedelta(days=15),
            content_hash="",
            status=AppointmentBatch.Status.CONFIGURING,
            version_no=2,
        )
        service_cls.return_value.update_draft.return_value = batch
        request = self.factory.patch(
            f"/api/v1/hr/appointments/batches/{self.batch_id}/",
            data=json.dumps(
                {
                    "expectedVersion": 1,
                    "policyVersionId": str(self.policy_id),
                    "publicityFrom": (now + timedelta(days=10)).isoformat(),
                    "publicityTo": (now + timedelta(days=15)).isoformat(),
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub()

        response = batch_configuration_api.update_batch(request, self.batch_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["ETag"], '"hr14-batch-v2"')
        resolve_tenant.assert_called_once_with(
            request, required_permission=batch_configuration_api.MANAGE_PERMISSION
        )
        kwargs = service_cls.return_value.update_draft.call_args.kwargs
        self.assertEqual(kwargs["expected_version"], 1)
        self.assertEqual(kwargs["patch"].policy_version_id, self.policy_id)
        self.assertEqual(kwargs["patch"].publicity_from, now + timedelta(days=10))

    @patch(
        "hr_appointment.batch_configuration_api.resolve_request_tenant",
        return_value=77,
    )
    @patch("hr_appointment.batch_configuration_api.AppointmentBatchConfigurationService")
    def test_version_conflict_is_http_409(self, service_cls, resolve_tenant):
        service_cls.return_value.update_draft.side_effect = AppointmentBatchConfigurationError(
            "APPOINTMENT_BATCH_VERSION_CONFLICT",
            "expected version 1, current version is 2",
        )
        request = self.factory.patch(
            f"/api/v1/hr/appointments/batches/{self.batch_id}/",
            data=json.dumps({"expectedVersion": 1, "name": "旧客户端"}),
            content_type="application/json",
        )
        request.user = UserStub()

        response = batch_configuration_api.update_batch(request, self.batch_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b"APPOINTMENT_BATCH_VERSION_CONFLICT", response.content)

    @patch(
        "hr_appointment.batch_configuration_api.resolve_request_tenant",
        return_value=77,
    )
    def test_unknown_field_and_missing_version_fail_before_service(self, resolve_tenant):
        request = self.factory.patch(
            f"/api/v1/hr/appointments/batches/{self.batch_id}/",
            data=json.dumps({"expectedVersion": 1, "inventedRule": True}),
            content_type="application/json",
        )
        request.user = UserStub()
        response = batch_configuration_api.update_batch(request, self.batch_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"APPOINTMENT_BATCH_PATCH_FIELD_UNKNOWN", response.content)

        request = self.factory.patch(
            f"/api/v1/hr/appointments/batches/{self.batch_id}/",
            data=json.dumps({"name": "缺版本"}),
            content_type="application/json",
        )
        request.user = UserStub()
        response = batch_configuration_api.update_batch(request, self.batch_id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"APPOINTMENT_BATCH_VERSION_INVALID", response.content)
