from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase

from hr_external.constants import ProvisioningOperation, ProvisioningStatus
from hr_external.integrations.base import ProviderResult, ProviderStatus
from hr_external.services.provisioning_dispatch_service import ProvisioningDispatchService


class ProvisioningDispatchContractTests(SimpleTestCase):
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalAccessGrant")
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalProvisioningRequest")
    def test_grant_dispatch_carries_durable_idempotency_and_receipt(self, request_model, grant_model):
        request = SimpleNamespace(
            id="request-1", tenant_id=77, engagement_id="engagement-1",
            target_system="ACADEMIC", operation=ProvisioningOperation.GRANT,
            scope_json={"roleCode": "ACADEMIC_TEACHER"},
            idempotency_key="grant:engagement-1:ACADEMIC",
        )
        grant = SimpleNamespace(
            id="grant-1", target_system="ACADEMIC", role_code="ACADEMIC_TEACHER",
            scope_json={"engagementId": "engagement-1"}, expires_at=None,
        )
        request_model.objects.filter.return_value.first.return_value = request
        grant_model.objects.filter.return_value.order_by.return_value.first.return_value = grant
        provider = Mock()
        provider.provision_grant.return_value = ProviderResult(
            status=ProviderStatus.OK, data={"receiptId": "iam-receipt-1"}
        )
        service = ProvisioningDispatchService(provider)
        service._claim_request = MagicMock(return_value=request)
        service._record_success = MagicMock(return_value="succeeded")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-1")

        self.assertEqual(outcome, "succeeded")
        sent = provider.provision_grant.call_args.kwargs
        self.assertEqual(sent["idempotency_key"], request.idempotency_key)
        self.assertEqual(sent["scope_json"], grant.scope_json)
        service._record_success.assert_called_once_with(
            request, grant, {"receiptId": "iam-receipt-1"}
        )

    def test_retry_contract_is_bounded_and_exponential(self):
        self.assertEqual(ProvisioningDispatchService.MAX_ATTEMPTS, 5)
        self.assertEqual(ProvisioningDispatchService.CLAIM_LEASE.total_seconds(), 300)
        self.assertEqual(ProvisioningStatus.FAILED_RETRYABLE, "FAILED_RETRYABLE")

    @patch("hr_external.services.access_service.AccessService.raise_revocation_risk")
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalAccessGrant")
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalProvisioningRequest")
    def test_terminal_revoke_failure_raises_critical_risk(
        self, request_model, grant_model, raise_risk
    ):
        request = SimpleNamespace(
            id="request-2",
            tenant_id=77,
            engagement_id="engagement-2",
            engagement_id_id="engagement-2",
            target_system="LIBRARY",
            operation=ProvisioningOperation.REVOKE,
            scope_json={"roleCode": "LIBRARY_EXTERNAL"},
            idempotency_key="revoke:grant-2",
        )
        grant = SimpleNamespace(
            id="grant-2",
            target_system="LIBRARY",
            role_code="LIBRARY_EXTERNAL",
            scope_json={"engagementId": "engagement-2"},
            expires_at=None,
        )
        request_model.objects.filter.return_value.first.return_value = request
        grant_model.objects.filter.return_value.order_by.return_value.first.return_value = grant
        provider = Mock()
        provider.revoke_grant.return_value = ProviderResult(
            status=ProviderStatus.ERROR,
            error_code="IAM_REVOKE_REJECTED",
        )
        service = ProvisioningDispatchService(provider)
        service._claim_request = MagicMock(return_value=request)
        service._record_failure = MagicMock(return_value="failed")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-2")

        self.assertEqual(outcome, "failed")
        raise_risk.assert_called_once_with(
            tenant_id=77,
            engagement_id="engagement-2",
            note="LIBRARY:IAM_REVOKE_REJECTED",
        )

    @patch("hr_external.services.access_service.AccessService.raise_revocation_risk")
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalAccessGrant")
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalProvisioningRequest")
    def test_missing_local_grant_during_revoke_still_raises_critical_risk(
        self, request_model, grant_model, raise_risk
    ):
        request = SimpleNamespace(
            id="request-3",
            tenant_id=77,
            engagement_id="engagement-3",
            engagement_id_id="engagement-3",
            target_system="PORTAL",
            operation=ProvisioningOperation.REVOKE,
            scope_json={"roleCode": "EXTERNAL_PORTAL"},
            idempotency_key="revoke:missing-grant",
        )
        request_model.objects.filter.return_value.first.return_value = request
        grant_model.objects.filter.return_value.order_by.return_value.first.return_value = None
        service = ProvisioningDispatchService(Mock())
        service._claim_request = MagicMock(return_value=request)
        service._record_failure = MagicMock(return_value="failed")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-3")

        self.assertEqual(outcome, "failed")
        raise_risk.assert_called_once_with(
            tenant_id=77,
            engagement_id="engagement-3",
            note="PORTAL:ACCESS_GRANT_NOT_FOUND",
        )

    @patch("hr_external.services.access_service.AccessService.raise_revocation_risk")
    @patch("hr_external.services.provisioning_dispatch_service.HrExternalAccessGrant")
    def test_revoke_success_without_receipt_fails_closed(self, grant_model, raise_risk):
        request = SimpleNamespace(
            id="request-4",
            tenant_id=77,
            engagement_id="engagement-4",
            engagement_id_id="engagement-4",
            target_system="PORTAL",
            operation=ProvisioningOperation.REVOKE,
            scope_json={"roleCode": "EXTERNAL_PORTAL"},
            idempotency_key="revoke:no-receipt",
        )
        grant = SimpleNamespace(
            id="grant-4",
            target_system="PORTAL",
            role_code="EXTERNAL_PORTAL",
            scope_json={"engagementId": "engagement-4"},
            expires_at=None,
        )
        grant_model.objects.filter.return_value.order_by.return_value.first.return_value = grant
        provider = Mock()
        provider.revoke_grant.return_value = ProviderResult(
            status=ProviderStatus.OK, data={"accepted": True}
        )
        service = ProvisioningDispatchService(provider)
        service._claim_request = MagicMock(return_value=request)
        service._record_failure = MagicMock(return_value="failed")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-4")

        self.assertEqual(outcome, "failed")
        raise_risk.assert_called_once_with(
            tenant_id=77,
            engagement_id="engagement-4",
            note="PORTAL:PROVIDER_RECEIPT_INVALID",
        )
