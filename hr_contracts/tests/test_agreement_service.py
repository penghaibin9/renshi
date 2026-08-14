from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_contracts.models import HrContractAgreement, HrContractVersion
from hr_contracts.services.agreement_service import AgreementService, ContractServiceError


class AgreementServiceTests(TestCase):
    def setUp(self):
        self.service = AgreementService(77, actor_user_id=9)

    @patch("hr_staff.models.HrEmploymentRelationship.objects")
    @patch("hr_staff.models.HrStaffMaster.objects")
    def test_staff_relationship_validation_is_explicitly_tenant_scoped(
        self, staff_objects, relationship_objects
    ):
        staff = SimpleNamespace(id="staff-1")
        staff_objects.filter.return_value.first.return_value = staff
        relationship_qs = MagicMock()
        relationship_qs.filter.return_value.first.return_value = SimpleNamespace(id="rel-1")
        relationship_objects.filter.return_value = relationship_qs

        self.service._validate_staff_relationship(
            staff_id="staff-1",
            relationship_id="rel-1",
            as_of=date(2026, 8, 10),
        )

        staff_objects.filter.assert_called_once_with(id="staff-1", tenant_id=77)
        relationship_objects.filter.assert_called_once_with(
            id="rel-1",
            tenant_id=77,
            staff_id_id="staff-1",
            status="ACTIVE",
            effective_from__lte=date(2026, 8, 10),
        )

    @patch("hr_contracts.services.agreement_service.HrContractVersion.objects")
    @patch("hr_contracts.services.agreement_service.HrContractAgreement.objects")
    def test_initial_sign_freezes_hash_and_cannot_overwrite_existing_version(
        self, agreement_objects, version_objects
    ):
        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.current_version_no = 0
        agreement.status = HrContractAgreement.Status.DRAFT
        agreement_objects.select_for_update.return_value.filter.return_value.first.return_value = agreement
        created = MagicMock()
        version_objects.create.return_value = created
        snapshot = {"salaryAuthority": False, "clauses": ["A", "B"]}

        result = self.service.sign_initial_version(
            agreement_id="agreement-1",
            effective_from=date(2026, 9, 1),
            effective_to=date(2027, 9, 1),
            signed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            signed_document_ref="doc://signed/1",
            content_snapshot=snapshot,
        )

        self.assertIs(result, created)
        kwargs = version_objects.create.call_args.kwargs
        self.assertEqual(len(kwargs["content_hash"]), 64)
        self.assertEqual(kwargs["content_snapshot_json"], snapshot)
        self.assertEqual(kwargs["status"], HrContractVersion.Status.SIGNED)
        self.assertEqual(agreement.current_version_no, 1)
        self.assertEqual(
            agreement.status, HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        )

        agreement.current_version_no = 1
        with self.assertRaises(ContractServiceError) as cm:
            self.service.sign_initial_version(
                agreement_id="agreement-1",
                effective_from=date(2026, 9, 1),
                effective_to=None,
                signed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                signed_document_ref="doc://signed/2",
                content_snapshot={"clauses": ["changed"]},
            )
        self.assertEqual(cm.exception.code, "CONTRACT_INITIAL_VERSION_ALREADY_EXISTS")

    @patch("hr_contracts.services.agreement_service.HrContractVersion.objects")
    @patch("hr_contracts.services.agreement_service.HrContractAgreement.objects")
    def test_future_signed_version_cannot_be_marked_active(
        self, agreement_objects, version_objects
    ):
        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.current_version_no = 1
        agreement.status = HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        version = MagicMock()
        version.version_no = 1
        version.status = HrContractVersion.Status.SIGNED
        version.effective_from = date(2026, 9, 1)
        version.effective_to = None
        agreement_objects.select_for_update.return_value.filter.return_value.first.return_value = agreement
        version_objects.select_for_update.return_value.filter.return_value.first.return_value = version

        with self.assertRaises(ContractServiceError) as cm:
            self.service.activate_initial_version(
                agreement_id="agreement-1",
                version_id="version-1",
                as_of=date(2026, 8, 10),
            )

        self.assertEqual(cm.exception.code, "CONTRACT_NOT_EFFECTIVE_YET")
        version.save.assert_not_called()

    @patch("hr_contracts.services.agreement_service.HrContractVersion.objects")
    @patch("hr_contracts.services.agreement_service.HrContractAgreement.objects")
    def test_activation_is_locked_tenant_scoped_and_idempotent(
        self, agreement_objects, version_objects
    ):
        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.current_version_no = 1
        agreement.status = HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        version = MagicMock()
        version.version_no = 1
        version.status = HrContractVersion.Status.SIGNED
        version.effective_from = date(2026, 8, 1)
        version.effective_to = None
        agreement_objects.select_for_update.return_value.filter.return_value.first.return_value = agreement
        version_objects.select_for_update.return_value.filter.return_value.first.return_value = version

        result = self.service.activate_initial_version(
            agreement_id="agreement-1",
            version_id="version-1",
            as_of=date(2026, 8, 10),
        )

        self.assertIs(result, version)
        agreement_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="agreement-1", tenant_id=77
        )
        version_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="version-1", tenant_id=77, agreement_id="agreement-1"
        )
        self.assertEqual(version.status, HrContractVersion.Status.EFFECTIVE)
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
