"""Atomic aggregate-root guards for HR10 programs and practice projects."""

import inspect

from django.test import SimpleTestCase

from hr10_development.api import practice, programs


class ProgramPracticeApiMutationContractTests(SimpleTestCase):
    def test_practice_project_and_version_writes_are_atomic(self):
        for view in (practice.create_project, practice.create_project_version, practice.publish_project):
            source = inspect.getsource(view)
            self.assertIn("with transaction.atomic()", source)
            self.assertIn("select_for_update()", source)
        self.assertIn("PRACTICE_VERSION_REQUIRED", inspect.getsource(practice.publish_project))

    def test_placement_requires_published_tenant_version_and_valid_range(self):
        source = inspect.getsource(practice.create_placement)

        self.assertIn("published_at__isnull=False", source)
        self.assertIn("project_version_id=version.id", source)
        self.assertIn("placement.capacity < 1", source)
        self.assertIn("placement.end_date < placement.start_date", source)

    def test_assignment_serializes_capacity_and_rejects_duplicates(self):
        source = inspect.getsource(practice.create_assignment)

        self.assertIn("HrEnterprisePracticePlacement.objects.select_for_update()", source)
        self.assertIn("PRACTICE_ASSIGNMENT_DUPLICATE", source)
        self.assertIn("PRACTICE_CAPACITY_FULL", source)
        self.assertIn("provider_org_id=project.provider_org_id", source)

    def test_program_publish_freezes_current_version_atomically(self):
        source = inspect.getsource(programs.publish_program)

        self.assertIn("HrLearningProgram.objects.select_for_update()", source)
        self.assertIn("ProgramVersionStatus.PUBLISHED", source)
        self.assertIn("ProgramVersionStatus.SUPERSEDED", source)
        self.assertIn("PROGRAM_VERSION_REQUIRED", source)

    def test_offering_lifecycle_is_locked_and_fail_closed(self):
        create_source = inspect.getsource(programs.create_offering)
        open_source = inspect.getsource(programs.open_enrollment)
        cancel_source = inspect.getsource(programs.cancel_offering)

        self.assertIn("status=ProgramVersionStatus.PUBLISHED", create_source)
        self.assertIn("HrLearningOffering.objects.select_for_update()", open_source)
        self.assertIn("ENROLLMENT_WINDOW_CLOSED", open_source)
        self.assertIn("OFFERING_CAPACITY_REQUIRED", open_source)
        self.assertIn("OFFERING_HAS_ACTIVE_ENROLLMENTS", cancel_source)
