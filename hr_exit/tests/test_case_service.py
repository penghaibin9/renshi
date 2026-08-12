from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_exit.models import ExitCase
from hr_exit.services.case_service import ExitCaseError, ExitCaseService


class ExitCaseServiceTests(TestCase):
    def _case(self, status):
        case = MagicMock()
        case.id = "case-1"
        case.status = status
        case.requested_date = date(2026, 8, 1)
        case.last_working_date = date(2026, 8, 31)
        case.planned_employment_end_date = date(2026, 9, 1)
        return case

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_submit_is_tenant_scoped(self, case_objects):
        case = self._case(ExitCase.Status.DRAFT)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        ExitCaseService(77, actor_user_id=9).submit("case-1")

        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        self.assertEqual(case.status, ExitCase.Status.SUBMITTED)

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_return_is_not_reject(self, case_objects):
        returned = self._case(ExitCase.Status.SUBMITTED)
        rejected = self._case(ExitCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            returned,
            rejected,
        ]
        service = ExitCaseService(77)

        service.return_for_correction("return")
        service.reject("reject")

        self.assertEqual(returned.status, ExitCase.Status.RETURNED)
        self.assertEqual(rejected.status, ExitCase.Status.REJECTED)

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_approval_requires_employment_end_date(self, case_objects):
        case = self._case(ExitCase.Status.SUBMITTED)
        case.planned_employment_end_date = None
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "required before approval"):
            ExitCaseService(77).approve("case-1")

        case.save.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_last_working_date_cannot_follow_employment_end(self, case_objects):
        case = self._case(ExitCase.Status.SUBMITTED)
        case.last_working_date = date(2026, 9, 2)
        case.planned_employment_end_date = date(2026, 9, 1)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "cannot be later"):
            ExitCaseService(77).approve("case-1")

        case.save.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_settlement_requires_handover(self, case_objects):
        case = self._case(ExitCase.Status.APPROVED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "cannot transition"):
            ExitCaseService(77).begin_settlement("case-1")

        case.save.assert_not_called()

    @patch("hr_exit.services.case_service.ExitCase.objects")
    def test_approved_case_cannot_use_preapproval_cancel(self, case_objects):
        case = self._case(ExitCase.Status.APPROVED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(ExitCaseError, "cannot transition"):
            ExitCaseService(77).cancel_before_approval("case-1")

        case.save.assert_not_called()
