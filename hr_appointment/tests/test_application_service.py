from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_appointment.models import AppointmentApplicationCase
from hr_appointment.services.application_service import (
    AppointmentApplicationError,
    AppointmentApplicationService,
)


class AppointmentApplicationServiceTests(TestCase):
    def _case(self, status):
        case = MagicMock()
        case.id = "case-1"
        case.status = status
        return case

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_submit_is_tenant_scoped(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.DRAFT)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        result = AppointmentApplicationService(77, actor_user_id=9).submit("case-1")

        self.assertIs(result, case)
        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="case-1", tenant_id=77
        )
        self.assertEqual(case.status, AppointmentApplicationCase.Status.SUBMITTED)

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_return_is_not_reject(self, case_objects):
        returned = self._case(AppointmentApplicationCase.Status.SUBMITTED)
        rejected = self._case(AppointmentApplicationCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.side_effect = [
            returned,
            rejected,
        ]
        service = AppointmentApplicationService(77)

        service.return_for_correction("return")
        service.reject_eligibility("reject")

        self.assertEqual(returned.status, AppointmentApplicationCase.Status.RETURNED)
        self.assertEqual(rejected.status, AppointmentApplicationCase.Status.REJECTED)

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_rejected_case_cannot_resubmit(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.REJECTED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(AppointmentApplicationError, "cannot transition"):
            AppointmentApplicationService(77).submit("case-1")

        case.save.assert_not_called()

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_review_requires_eligibility(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.SUBMITTED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaisesRegex(AppointmentApplicationError, "cannot transition"):
            AppointmentApplicationService(77).start_review("case-1")

        case.save.assert_not_called()

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_publicity_is_last_workflow_state_before_effect_service(self, case_objects):
        case = self._case(AppointmentApplicationCase.Status.PROPOSED)
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        AppointmentApplicationService(77).enter_publicity("case-1")

        self.assertEqual(case.status, AppointmentApplicationCase.Status.PUBLICITY)
        self.assertNotEqual(case.status, AppointmentApplicationCase.Status.EFFECTIVE)

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_missing_or_cross_tenant_case_fails_closed(self, case_objects):
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = None

        with self.assertRaisesRegex(AppointmentApplicationError, "not found"):
            AppointmentApplicationService(77).submit("foreign")

        case_objects.select_for_update.return_value.filter.assert_called_once_with(
            id="foreign", tenant_id=77
        )
