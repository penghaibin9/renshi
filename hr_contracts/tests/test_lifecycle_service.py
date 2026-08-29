from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_contracts.models import HrContractAgreement, HrContractCase, HrContractVersion
from hr_contracts.services.agreement_service import ContractServiceError
from hr_contracts.services.lifecycle_service import ContractLifecycleService


class ContractLifecycleServiceTests(TestCase):
    def setUp(self):
        self.service = ContractLifecycleService(77, actor_user_id=9)

    @patch("hr_contracts.services.lifecycle_service.HrContractCase.objects")
    def test_case_lookup_is_fail_closed_and_tenant_scoped(self, case_objects):
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = None

        with self.assertRaises(ContractServiceError) as cm:
            self.service._case("case-1")

        self.assertEqual(cm.exception.code, "CONTRACT_CASE_NOT_FOUND")
        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )

    @patch("hr_contracts.services.lifecycle_service.HrContractVersion.objects")
    @patch("hr_contracts.services.lifecycle_service.emit_registered_event")
    def test_renewal_signs_append_only_successor_without_overwriting_previous(
        self, emit_event, version_objects
    ):
        case = MagicMock()
        case.id = "case-1"
        case.case_type = HrContractCase.CaseType.RENEW
        case.status = HrContractCase.Status.APPROVED
        case.agreement_id = "agreement-1"
        case.requested_effective_from = date(2027, 1, 1)
        case.requested_effective_to = date(2028, 1, 1)

        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.current_version_no = 1
        agreement.status = HrContractAgreement.Status.RENEWAL_IN_PROGRESS

        previous = MagicMock()
        previous.id = "version-1"
        previous.status = HrContractVersion.Status.EFFECTIVE
        previous.effective_from = date(2026, 1, 1)
        previous.effective_to = date(2027, 1, 1)

        created = MagicMock()
        version_objects.create.return_value = created

        with patch.object(self.service, "_case", return_value=case), patch.object(
            self.service, "_agreement", return_value=agreement
        ), patch.object(
            self.service, "_current_effective_version", return_value=previous
        ):
            result = self.service.sign_successor_version(
                case_id="case-1",
                signed_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
                signed_document_ref="doc://renewal/1",
                content_snapshot={"clauses": ["renewed"]},
            )

        self.assertIs(result, created)
        kwargs = version_objects.create.call_args.kwargs
        self.assertEqual(kwargs["version_no"], 2)
        self.assertEqual(kwargs["status"], HrContractVersion.Status.SIGNED)
        self.assertEqual(kwargs["supersedes_version_id"], "version-1")
        self.assertEqual(kwargs["source_business_type"], HrContractCase.CaseType.RENEW)
        self.assertEqual(len(kwargs["content_hash"]), 64)
        previous.save.assert_not_called()
        self.assertEqual(agreement.current_version_no, 2)
        self.assertEqual(
            agreement.status, HrContractAgreement.Status.SIGNED_WAITING_EFFECTIVE
        )
        self.assertEqual(case.status, HrContractCase.Status.EFFECT_PENDING)

    def test_future_successor_cannot_activate_early(self):
        case = MagicMock()
        case.status = HrContractCase.Status.EFFECT_PENDING
        case.agreement_id = "agreement-1"
        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.current_version_no = 2
        version = MagicMock()
        version.version_no = 2
        version.status = HrContractVersion.Status.SIGNED
        version.effective_from = date(2027, 1, 1)
        version.supersedes_version_id = "version-1"

        qs = MagicMock()
        qs.first.return_value = version
        with patch.object(self.service, "_case", return_value=case), patch.object(
            self.service, "_agreement", return_value=agreement
        ), patch(
            "hr_contracts.services.lifecycle_service.HrContractVersion.objects"
        ) as objects:
            objects.select_for_update.return_value.filter.return_value = qs
            with self.assertRaises(ContractServiceError) as cm:
                self.service.activate_successor_version(
                    case_id="case-1",
                    version_id="version-2",
                    as_of=date(2026, 12, 31),
                )

        self.assertEqual(cm.exception.code, "CONTRACT_NOT_EFFECTIVE_YET")
        version.save.assert_not_called()

    @patch("hr_contracts.services.lifecycle_service.emit_registered_event")
    def test_activation_supersedes_previous_then_publishes_successor(self, emit_event):
        case = MagicMock()
        case.id = "case-1"
        case.status = HrContractCase.Status.EFFECT_PENDING
        case.agreement_id = "agreement-1"
        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.current_version_no = 2

        successor = MagicMock()
        successor.id = "version-2"
        successor.version_no = 2
        successor.status = HrContractVersion.Status.SIGNED
        successor.effective_from = date(2027, 1, 1)
        successor.supersedes_version_id = "version-1"
        previous = MagicMock()
        previous.id = "version-1"
        previous.status = HrContractVersion.Status.EFFECTIVE
        previous.effective_to = None

        next_qs = MagicMock()
        next_qs.first.return_value = successor
        prev_qs = MagicMock()
        prev_qs.first.return_value = previous

        with patch.object(self.service, "_case", return_value=case), patch.object(
            self.service, "_agreement", return_value=agreement
        ), patch(
            "hr_contracts.services.lifecycle_service.HrContractVersion.objects"
        ) as objects:
            objects.select_for_update.return_value.filter.side_effect = [
                next_qs,
                prev_qs,
            ]
            result = self.service.activate_successor_version(
                case_id="case-1",
                version_id="version-2",
                as_of=date(2027, 1, 1),
            )

        self.assertIs(result, successor)
        self.assertEqual(previous.status, HrContractVersion.Status.SUPERSEDED)
        self.assertEqual(previous.effective_to, date(2027, 1, 1))
        self.assertEqual(successor.status, HrContractVersion.Status.EFFECTIVE)
        self.assertEqual(agreement.status, HrContractAgreement.Status.ACTIVE)
        self.assertEqual(case.status, HrContractCase.Status.EFFECTIVE)

    @patch("hr_contracts.services.lifecycle_service.emit_registered_event")
    def test_termination_requires_approved_case_and_effective_date(self, emit_event):
        case = MagicMock()
        case.case_type = HrContractCase.CaseType.TERMINATE
        case.status = HrContractCase.Status.APPROVED
        case.agreement_id = "agreement-1"
        case.requested_effective_from = date(2026, 10, 1)
        agreement = MagicMock()
        agreement.id = "agreement-1"
        agreement.status = HrContractAgreement.Status.ACTIVE
        current = MagicMock()
        current.id = "version-1"
        current.status = HrContractVersion.Status.EFFECTIVE
        current.effective_from = date(2026, 1, 1)
        current.effective_to = None

        with patch.object(self.service, "_case", return_value=case), patch.object(
            self.service, "_agreement", return_value=agreement
        ), patch.object(
            self.service, "_current_effective_version", return_value=current
        ):
            with self.assertRaises(ContractServiceError) as cm:
                self.service.effect_termination(
                    case_id="case-1", as_of=date(2026, 9, 30)
                )
            self.assertEqual(cm.exception.code, "CONTRACT_NOT_EFFECTIVE_YET")
            current.save.assert_not_called()

            result = self.service.effect_termination(
                case_id="case-1", as_of=date(2026, 10, 1)
            )

        self.assertIs(result, case)
        self.assertEqual(current.effective_to, date(2026, 10, 1))
        self.assertEqual(current.status, HrContractVersion.Status.TERMINATED)
        self.assertEqual(agreement.status, HrContractAgreement.Status.TERMINATED)
        self.assertEqual(case.status, HrContractCase.Status.EFFECTIVE)
