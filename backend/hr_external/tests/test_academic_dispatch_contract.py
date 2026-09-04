from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase

from hr_external.integrations.base import ProviderResult, ProviderStatus
from hr_external.models import HrExternalAcademicProvisioningRequest
from hr_external.services.academic_identity_service import AcademicIdentityService


class AcademicIdentityDispatchContractTests(SimpleTestCase):
    @patch(
        "hr_external.services.academic_identity_service."
        "HrExternalAcademicProvisioningRequest.objects"
    )
    def test_activation_uses_durable_idempotency_and_provider_teacher_id(self, request_objects):
        identity = SimpleNamespace(
            id="identity-1",
            external_teacher_no="EXT77-001",
            academic_teacher_id="",
            valid_from=date(2026, 9, 1),
            valid_to=date(2027, 7, 1),
        )
        request = SimpleNamespace(
            id="request-1",
            tenant_id=77,
            academic_identity_id=identity,
            operation=HrExternalAcademicProvisioningRequest.Operation.ACTIVATE,
            idempotency_key="academic-activate:identity-1",
        )
        request_objects.select_related.return_value.filter.return_value.first.return_value = request
        provider = Mock()
        provider.activate_teacher_identity.return_value = ProviderResult(
            status=ProviderStatus.OK,
            data={"receiptId": "jw-receipt-1", "academicTeacherId": "T20260001"},
        )
        service = AcademicIdentityService(provider)
        service._claim_request = MagicMock(return_value=request)
        service._record_success = MagicMock(return_value="succeeded")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-1")

        self.assertEqual(outcome, "succeeded")
        sent = provider.activate_teacher_identity.call_args.kwargs
        self.assertEqual(sent["idempotency_key"], request.idempotency_key)
        self.assertEqual(sent["external_teacher_no"], "EXT77-001")
        service._record_success.assert_called_once_with(
            request,
            identity,
            {"receiptId": "jw-receipt-1", "academicTeacherId": "T20260001"},
        )

    def test_retry_contract_is_bounded(self):
        self.assertEqual(AcademicIdentityService.MAX_ATTEMPTS, 5)
        self.assertEqual(AcademicIdentityService.CLAIM_LEASE.total_seconds(), 300)

    @patch(
        "hr_external.services.academic_identity_service."
        "HrExternalAcademicProvisioningRequest.objects"
    )
    def test_deactivation_uses_external_number_when_provider_id_is_missing(
        self, request_objects
    ):
        identity = SimpleNamespace(
            id="identity-2",
            external_teacher_no="EXT77-002",
            academic_teacher_id="",
        )
        request = SimpleNamespace(
            id="request-2",
            tenant_id=77,
            academic_identity_id=identity,
            operation=HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE,
            idempotency_key="academic-deactivate:identity-2",
        )
        request_objects.select_related.return_value.filter.return_value.first.return_value = request
        provider = Mock()
        provider.deactivate_teacher_identity.return_value = ProviderResult(
            status=ProviderStatus.OK,
            data={"receiptId": "jw-receipt-2"},
        )
        service = AcademicIdentityService(provider)
        service._claim_request = MagicMock(return_value=request)
        service._record_success = MagicMock(return_value="succeeded")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-2")

        self.assertEqual(outcome, "succeeded")
        sent = provider.deactivate_teacher_identity.call_args.kwargs
        self.assertEqual(sent["academic_teacher_id"], "")
        self.assertEqual(sent["external_teacher_no"], "EXT77-002")

    @patch("hr_external.services.access_service.AccessService.raise_revocation_risk")
    def test_deactivation_success_without_receipt_fails_closed(self, raise_risk):
        identity = SimpleNamespace(
            id="identity-3",
            external_teacher_no="EXT77-003",
            academic_teacher_id="T-3",
            engagement_id_id="engagement-3",
        )
        request = SimpleNamespace(
            id="request-3",
            tenant_id=77,
            academic_identity_id=identity,
            operation=HrExternalAcademicProvisioningRequest.Operation.DEACTIVATE,
            idempotency_key="academic-deactivate:identity-3",
        )
        provider = Mock()
        provider.deactivate_teacher_identity.return_value = ProviderResult(
            status=ProviderStatus.OK, data={"accepted": True}
        )
        service = AcademicIdentityService(provider)
        service._claim_request = MagicMock(return_value=request)
        service._record_failure = MagicMock(return_value="failed")

        outcome = service.dispatch_one(tenant_id=77, request_id="request-3")

        self.assertEqual(outcome, "failed")
        raise_risk.assert_called_once_with(
            tenant_id=77,
            engagement_id="engagement-3",
            note="ACADEMIC_IDENTITY:PROVIDER_RECEIPT_INVALID",
        )
