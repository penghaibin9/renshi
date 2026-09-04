"""State and concurrency guards for HR10 requests, seats, and completions."""

import inspect

from django.test import SimpleTestCase

from hr10_development.api import enrollments, requests
from hr10_development.services.completion_service import CompletionService
from hr10_development.services.enrollment_service import EnrollmentService
from hr10_development.services.offering_service import OfferingService


class TrainingLifecycleMutationContractTests(SimpleTestCase):
    def test_request_creation_scopes_staff_program_and_offering_atomically(self):
        source = inspect.getsource(requests.create_request)

        self.assertIn("with transaction.atomic()", source)
        self.assertIn("HrStaffMaster.objects.select_for_update()", source)
        self.assertIn("REQUEST_PROGRAM_OFFERING_MISMATCH", source)
        self.assertIn("r.full_clean()", source)

    def test_enrollment_service_locks_offering_before_duplicate_and_capacity_checks(self):
        source = inspect.getsource(EnrollmentService.enroll)

        self.assertIn("HrLearningOffering.objects.select_for_update()", source)
        self.assertIn("OfferingStatus.OPEN", source)
        self.assertIn("DevelopmentErrorCode.DUPLICATE_ENROLLMENT", source)
        self.assertIn("HrStaffMaster.objects.filter", source)

    def test_waitlist_only_opens_after_regular_capacity_is_exhausted(self):
        waitlist_source = inspect.getsource(EnrollmentService.waitlist)
        seat_source = inspect.getsource(OfferingService.occupy_seat)

        self.assertIn("OfferingStatus.WAITLIST_OPEN", waitlist_source)
        self.assertIn("offering.capacity > 0", waitlist_source)
        self.assertIn("OfferingStatus.WAITLIST_OPEN", seat_source)

    def test_completion_submission_does_not_prematurely_complete_enrollment(self):
        source = inspect.getsource(enrollments.complete_enrollment)

        self.assertIn("HrLearningEnrollment.objects.select_for_update()", source)
        self.assertIn("program_version_id=offering.program_version_id", source)
        self.assertNotIn("enrollment.enrollment_status = EnrollmentStatus.COMPLETED", source)

    def test_only_verified_completion_marks_enrollment_completed(self):
        source = inspect.getsource(enrollments.verify_completion)

        self.assertIn('result["status"] in {"VERIFIED", "COMPLETION_ALREADY_VERIFIED"}', source)
        self.assertIn("enrollment.enrollment_status = EnrollmentStatus.COMPLETED", source)
        self.assertIn("INVALID_VERIFICATION_SOURCE", source)

    def test_completion_service_locks_fresh_record(self):
        source = inspect.getsource(CompletionService)

        self.assertIn("objects.select_for_update().get", source)
