from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_title.models import TitleApplicationCase
from hr_title.services.application_service import (
    TitleApplicationError,
    TitleApplicationService,
)


class TitleApplicationServiceTests(TestCase):
    def _case(self, status):
        case = MagicMock()
        case.id = "case-1"
        case.status = status
        return case

    @patch("hr_title.services.application_service.TitleApplicationCase.objects")
    def test_submit_is_tenant_scoped_and_sets_submission_time(self, case_objects):
        case = self._case(TitleApplicationCase.Status.DRAFT)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        result = TitleApplicationService(77, actor_user_id=9).submit("case-1")

        self.assertIs(result, case)
        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        self.assertEqual(case.status, TitleApplicationCase.Status.SUBMITTED)
        self.assertIsNotNone(case.submitted_at)
        case.save.assert_called_once_with(
            update_fields=["status", "submitted_at", "updated_by", "updated_at"]
        )

    @patch("hr_title.services.application_service.TitleApplicationCase.objects")
    def test_return_and_reject_are_distinct_transitions(self, case_objects):
        returned = self._case(TitleApplicationCase.Status.SUBMITTED)
        rejected = self._case(TitleApplicationCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            returned,
            rejected,
        ]
        service = TitleApplicationService(77, actor_user_id=9)

        service.return_for_correction("case-return")
        service.reject_eligibility("case-reject")

        self.assertEqual(returned.status, TitleApplicationCase.Status.RETURNED)
        self.assertEqual(rejected.status, TitleApplicationCase.Status.REJECTED)
        self.assertNotEqual(returned.status, rejected.status)

    @patch("hr_title.services.application_service.TitleApplicationCase.objects")
    def test_returned_case_can_resubmit_but_rejected_case_cannot(self, case_objects):
        returned = self._case(TitleApplicationCase.Status.RETURNED)
        rejected = self._case(TitleApplicationCase.Status.REJECTED)
        case_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            returned,
            rejected,
        ]
        service = TitleApplicationService(77)

        service.submit("returned")
        with self.assertRaisesRegex(TitleApplicationError, "cannot transition"):
            service.submit("rejected")

        self.assertEqual(returned.status, TitleApplicationCase.Status.SUBMITTED)
        rejected.save.assert_not_called()

    @patch("hr_title.services.application_service.TitleApplicationCase.objects")
    def test_only_eligible_case_can_enter_review(self, case_objects):
        case = self._case(TitleApplicationCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(TitleApplicationError, "cannot transition"):
            TitleApplicationService(77).start_review("case-1")

        case.save.assert_not_called()

    @patch("hr_title.services.application_service.TitleApplicationCase.objects")
    def test_publicity_requires_proposed_result(self, case_objects):
        case = self._case(TitleApplicationCase.Status.UNDER_REVIEW)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(TitleApplicationError, "cannot transition"):
            TitleApplicationService(77).enter_publicity("case-1")

        case.save.assert_not_called()

    @patch("hr_title.services.application_service.TitleApplicationCase.objects")
    def test_missing_or_cross_tenant_case_fails_closed(self, case_objects):
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(TitleApplicationError, "application case not found"):
            TitleApplicationService(77).submit("foreign-case")

        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="foreign-case", tenant_id=77
        )
