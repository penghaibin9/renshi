import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from hr_appointment import application_api
from hr_appointment.api import HrAppointmentAccessError
from hr_appointment.models import AppointmentApplicationCase, AppointmentBatch
from hr_appointment.services.application_service import (
    AppointmentApplicationError,
    AppointmentApplicationService,
)
from hr_staff.models import HrAccountLink, HrPerson, HrStaffMaster


class UserStub:
    is_authenticated = True
    is_superuser = False

    def __init__(self, user_id=88, permissions=()):
        self.id = user_id
        self.permissions = set(permissions)

    def has_perm(self, code):
        return code in self.permissions


class ApplicantIdentityResolverTests(TestCase):
    def _staff(self, *, person_name, staff_no):
        person = HrPerson.objects.create(tenant_id=77, legal_name=person_name)
        staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=person,
            staff_no=staff_no,
        )
        return person, staff

    def test_application_only_user_resolves_unique_active_hr03_person(self):
        person, staff = self._staff(person_name="本人", staff_no="SELF-001")
        HrAccountLink.objects.create(
            tenant_id=77,
            staff_id=staff,
            auth_user_id=88,
            link_status=HrAccountLink.LinkStatus.ACTIVE,
        )
        request = SimpleNamespace(
            user=UserStub(88, {application_api.APPLICATION_PERMISSION})
        )

        resolved = application_api._resolve_applicant_person_id(request, 77)

        self.assertEqual(resolved, person.id)

    def test_missing_or_ambiguous_hr03_identity_fails_closed(self):
        request = SimpleNamespace(
            user=UserStub(88, {application_api.APPLICATION_PERMISSION})
        )
        with self.assertRaises(HrAppointmentAccessError) as ctx:
            application_api._resolve_applicant_person_id(request, 77)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_SELF_IDENTITY_REQUIRED")

        _, staff_a = self._staff(person_name="A", staff_no="A-001")
        _, staff_b = self._staff(person_name="B", staff_no="B-001")
        for staff in (staff_a, staff_b):
            HrAccountLink.objects.create(
                tenant_id=77,
                staff_id=staff,
                auth_user_id=88,
                link_status=HrAccountLink.LinkStatus.ACTIVE,
            )
        with self.assertRaises(HrAppointmentAccessError) as ctx:
            application_api._resolve_applicant_person_id(request, 77)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_SELF_IDENTITY_AMBIGUOUS")

    def test_manage_permission_is_explicit_on_behalf_bypass(self):
        request = SimpleNamespace(
            user=UserStub(
                88,
                {
                    application_api.APPLICATION_PERMISSION,
                    application_api.MANAGE_PERMISSION,
                },
            )
        )
        self.assertIsNone(application_api._resolve_applicant_person_id(request, 77))


class ApplicantTransitionScopeTests(SimpleTestCase):
    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_submit_rejects_other_person_inside_locked_service_boundary(self, case_objects):
        case = MagicMock()
        case.person_id = uuid.uuid4()
        case.status = AppointmentApplicationCase.Status.DRAFT
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaises(AppointmentApplicationError) as ctx:
            AppointmentApplicationService(77).submit(
                "case-1",
                actor_person_id=uuid.uuid4(),
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_APPLICATION_SELF_ONLY")
        case.save.assert_not_called()

    @patch("hr_appointment.services.application_service.AppointmentApplicationCase.objects")
    def test_withdraw_rejects_other_person_inside_locked_service_boundary(self, case_objects):
        case = MagicMock()
        case.person_id = uuid.uuid4()
        case.status = AppointmentApplicationCase.Status.SUBMITTED
        case_objects.select_for_update.return_value.filter.return_value.first.return_value = case

        with self.assertRaises(AppointmentApplicationError) as ctx:
            AppointmentApplicationService(77).withdraw(
                "case-1",
                actor_person_id=uuid.uuid4(),
            )

        self.assertEqual(ctx.exception.code, "APPOINTMENT_APPLICATION_SELF_ONLY")
        case.save.assert_not_called()


class ApplicantApiSelfScopeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.person_id = uuid.uuid4()
        self.policy_id = uuid.uuid4()
        self.case_id = uuid.uuid4()

    @patch("hr_appointment.application_api._resolve_applicant_person_id")
    @patch("hr_appointment.application_api._context")
    def test_create_rejects_cross_person_before_application_service(self, context, resolve_self):
        service = MagicMock()
        context.return_value = (77, service)
        resolve_self.return_value = self.person_id
        request = self.factory.post(
            "/api/v1/hr/appointments/applications/",
            data=json.dumps(
                {
                    "caseNo": "CASE-OTHER",
                    "personId": str(uuid.uuid4()),
                    "policyVersionId": str(self.policy_id),
                    "positionInstanceId": 1001,
                    "batchNo": "B-2026-01",
                }
            ),
            content_type="application/json",
        )
        request.user = UserStub(88, {application_api.APPLICATION_PERMISSION})

        response = application_api.create_application(request)

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"APPOINTMENT_APPLICATION_SELF_ONLY", response.content)
        service.create_draft.assert_not_called()

    @patch("hr_appointment.application_api._resolve_applicant_person_id")
    @patch("hr_appointment.application_api._context")
    def test_submit_passes_self_person_into_transactional_service_check(
        self, context, resolve_self
    ):
        service = MagicMock()
        case = SimpleNamespace(
            id=self.case_id,
            case_no="CASE-SELF",
            person_id=self.person_id,
            policy_version_id=self.policy_id,
            position_instance_id=1001,
            batch_no="B-2026-01",
            requested_level_code="PT-7",
            status=AppointmentApplicationCase.Status.SUBMITTED,
        )
        service.submit.return_value = case
        context.return_value = (77, service)
        resolve_self.return_value = self.person_id
        request = self.factory.post("/submit")
        request.user = UserStub(88, {application_api.APPLICATION_PERMISSION})

        response = application_api.submit_application(request, self.case_id)

        self.assertEqual(response.status_code, 200)
        service.submit.assert_called_once_with(
            self.case_id,
            actor_person_id=self.person_id,
        )
