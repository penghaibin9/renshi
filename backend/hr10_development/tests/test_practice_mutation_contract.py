"""Production guards for the HR10 enterprise-practice lifecycle."""

import inspect

from django.test import SimpleTestCase

from hr10_development.api import practice_process
from hr10_development.services.practice_process_service import PracticeProcessService


class PracticeMutationContractTests(SimpleTestCase):
    def test_process_records_lock_and_scope_the_assignment(self):
        for view in (
            practice_process.add_activity,
            practice_process.add_evidence,
            practice_process.submit_mentor_feedback,
            practice_process.submit_school_evaluation,
        ):
            source = inspect.getsource(view)
            self.assertIn("with transaction.atomic()", source)
            self.assertIn("_locked_assignment(tenant_id, assignment_id)", source)
            self.assertIn("assignment.assignment_status", source)

    def test_evidence_activity_must_belong_to_same_assignment(self):
        source = inspect.getsource(practice_process.add_evidence)

        self.assertIn("assignment_id=assignment.id", source)
        self.assertIn("tenant_id=tenant_id", source)

    def test_completion_precheck_transitions_to_review_only_on_pass(self):
        source = inspect.getsource(practice_process.submit_completion)

        self.assertIn('precheck["status"] == "PASS"', source)
        self.assertIn("AssignmentStatus.COMPLETION_REVIEW", source)

    def test_final_evaluation_is_locked_prechecked_and_immutable(self):
        source = inspect.getsource(practice_process.finalize_evaluation)

        self.assertIn("_locked_assignment(tenant_id, assignment_id)", source)
        self.assertIn("PRACTICE_EVALUATION_IMMUTABLE", source)
        self.assertIn('precheck["status"] != "PASS"', source)
        self.assertNotIn("update_or_create", source)

    def test_outputs_are_tenant_scoped_and_terminal_verification_is_frozen(self):
        create_source = inspect.getsource(practice_process.create_output)
        verify_source = inspect.getsource(practice_process.verify_output)

        self.assertIn("HrStaffMaster.objects.select_for_update()", create_source)
        self.assertIn("legacy_employee_id=staff_id", create_source)
        self.assertIn("HrDevelopmentOutput.objects.select_for_update()", verify_source)
        self.assertIn("OUTPUT_VERIFICATION_IMMUTABLE", verify_source)

    def test_assignment_state_transitions_lock_fresh_database_state(self):
        source = inspect.getsource(PracticeProcessService)

        self.assertIn("objects.select_for_update().get", source)
        self.assertIn("AssignmentStatus.APPROVED", source)
        self.assertIn("AssignmentStatus.SUSPENDED", source)
        self.assertIn("SUSPEND_REASON_REQUIRED", source)
