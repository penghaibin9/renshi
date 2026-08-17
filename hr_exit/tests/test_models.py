from django.test import SimpleTestCase

from hr_exit.models import ExitCase, ExitFact, RetirementFact


class Hr16ModelContractTests(SimpleTestCase):
    def test_returned_and_rejected_are_distinct_states(self):
        assert ExitCase.Status.RETURNED != ExitCase.Status.REJECTED

    def test_exit_dates_are_not_collapsed_into_one_field(self):
        names = {field.name for field in ExitFact._meta.fields}
        assert "employment_end_date" in names
        assert "last_working_date" in names
        assert "access_end_at" in names

    def test_retirement_keeps_pension_processing_separate_from_effective_fact(self):
        assert "COMPLETED" in RetirementFact.PensionStatus.values
        assert "EFFECTIVE" in ExitFact.Status.values

    def test_tenant_is_fail_closed_before_database_write(self):
        case = ExitCase(
            tenant_id=None,
            case_no="EXIT-1",
            person_id="00000000-0000-0000-0000-000000000001",
            employment_relationship_id="00000000-0000-0000-0000-000000000002",
            exit_type=ExitCase.ExitType.RESIGNATION,
        )
        with self.assertRaisesRegex(ValueError, "tenant_id is required"):
            case.save()
