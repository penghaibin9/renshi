from django.test import SimpleTestCase

from hr_appointment.models import (
    AppointmentApplicationCase,
    AppointmentPolicyVersion,
    PositionAppointmentFact,
)


class Hr14ModelContractTests(SimpleTestCase):
    def test_returned_and_rejected_are_distinct_states(self):
        assert AppointmentApplicationCase.Status.RETURNED != AppointmentApplicationCase.Status.REJECTED

    def test_fact_states_do_not_include_payroll_states(self):
        assert set(PositionAppointmentFact.Status.values) == {
            "EFFECTIVE",
            "REVISED",
            "ENDED",
            "REVOKED",
        }

    def test_policy_has_named_version_constraint(self):
        names = {constraint.name for constraint in AppointmentPolicyVersion._meta.constraints}
        assert "uq_hr14_policy_tenant_code_ver" in names

    def test_tenant_is_fail_closed_before_database_write(self):
        fact = PositionAppointmentFact(
            tenant_id=None,
            appointment_no="APPT-1",
            person_id="00000000-0000-0000-0000-000000000001",
            position_instance_id="00000000-0000-0000-0000-000000000002",
            application_case_id="00000000-0000-0000-0000-000000000003",
            effective_from="2026-09-01",
        )
        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            fact.save()
