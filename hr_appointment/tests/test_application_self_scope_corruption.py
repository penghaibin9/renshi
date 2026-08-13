from types import SimpleNamespace

from django.test import TestCase

from hr_appointment import application_api
from hr_appointment.api import HrAppointmentAccessError
from hr_staff.models import HrAccountLink, HrPerson, HrStaffMaster


class UserStub:
    id = 88
    is_authenticated = True
    is_superuser = False

    def has_perm(self, code):
        return False


class ApplicantCorruptedLinkScopeTests(TestCase):
    def test_link_tenant_cannot_mask_foreign_staff_and_person(self):
        foreign_person = HrPerson.objects.create(tenant_id=88, legal_name="外校人员")
        foreign_staff = HrStaffMaster.objects.create(
            tenant_id=88,
            person_id=foreign_person,
            staff_no="FOREIGN-001",
        )
        # Bypass model clean intentionally to simulate historical/corrupted data.
        HrAccountLink.objects.create(
            tenant_id=77,
            staff_id=foreign_staff,
            auth_user_id=88,
            link_status=HrAccountLink.LinkStatus.ACTIVE,
        )
        request = SimpleNamespace(user=UserStub())

        with self.assertRaises(HrAppointmentAccessError) as ctx:
            application_api._resolve_applicant_person_id(request, 77)

        self.assertEqual(ctx.exception.code, "APPOINTMENT_SELF_IDENTITY_REQUIRED")
