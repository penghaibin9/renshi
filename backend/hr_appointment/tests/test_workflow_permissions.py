from django.contrib.auth.models import Permission
from django.test import TestCase


class AppointmentWorkflowPermissionTests(TestCase):
    def test_manage_and_application_permissions_exist_after_migrate(self):
        codes = set(
            Permission.objects.filter(
                content_type__app_label="hr_appointment",
                content_type__model="appointmentpolicyversion",
                codename__in=[
                    "hr.appointment.application",
                    "hr.appointment.manage",
                ],
            ).values_list("codename", flat=True)
        )
        self.assertEqual(
            codes,
            {"hr.appointment.application", "hr.appointment.manage"},
        )
