from datetime import datetime, time

from django.test import TestCase
from django.utils import timezone

from hr10_development.constants import ScheduleConflictResult
from hr10_development.providers.base import ProviderStatus
from hr10_development.providers.time_provider import Hr11TimeConflictProvider
from hr10_development.services.enrollment_service import EnrollmentService
from hr10_development.models.offering import HrLearningOffering
from hr_time.models import (
    HrLeaveRequest,
    HrLeaveType,
    HrScheduleAssignment,
    HrShiftDefinition,
    HrShiftVersion,
)
from hr_staff.models import HrPerson, HrStaffMaster


def _at(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class Hr11TimeConflictProviderTests(TestCase):
    def setUp(self):
        self.provider = Hr11TimeConflictProvider()
        self.day = timezone.localdate().replace(day=15)
        person = HrPerson.objects.create(tenant_id=71, legal_name="冲突测试教师")
        HrStaffMaster.objects.create(
            tenant_id=71,
            person_id=person,
            staff_no="TIME-501",
            legacy_employee_id=501,
        )

    def test_invalid_or_unbounded_window_fails_closed(self):
        result = self.provider.check_conflict(
            "not-a-number", 71, _at(self.day, 9), _at(self.day, 8)
        )

        self.assertEqual(result.result, ScheduleConflictResult.BLOCKED)
        self.assertEqual(result.conflicts[0]["type"], "INVALID_TIME_QUERY")

    def test_approved_leave_blocks_and_is_tenant_scoped(self):
        leave_type = HrLeaveType.objects.create(
            tenant_id=71, code="ANNUAL", name="Annual"
        )
        HrLeaveRequest.objects.create(
            tenant_id=71,
            staff_master_id=501,
            leave_type=leave_type,
            start_at=self.day,
            end_at=self.day,
            requested_amount=1,
            status="APPROVED",
        )

        blocked = self.provider.check_conflict(
            "501", 71, _at(self.day, 9), _at(self.day, 11)
        )
        other_tenant = self.provider.check_conflict(
            "501", 72, _at(self.day, 9), _at(self.day, 11)
        )

        self.assertEqual(blocked.result, ScheduleConflictResult.BLOCKED)
        self.assertEqual(blocked.conflicts[0]["type"], "APPROVED_LEAVE")
        self.assertEqual(other_tenant.result, ScheduleConflictResult.PASS)

    def test_shift_overlap_warns_but_non_overlap_passes(self):
        shift_definition = HrShiftDefinition.objects.create(
            tenant_id=71, code="DAY", name="Day"
        )
        shift = HrShiftVersion.objects.create(
            tenant_id=71,
            shift=shift_definition,
            start_time=time(8),
            end_time=time(17),
            effective_from=self.day,
            published_at=timezone.now(),
        )
        HrScheduleAssignment.objects.create(
            tenant_id=71,
            staff_master_id=501,
            shift_version=shift,
            effective_from=self.day,
            effective_to=self.day,
        )

        warning = self.provider.check_conflict(
            "501", 71, _at(self.day, 9), _at(self.day, 11)
        )
        passed = self.provider.check_conflict(
            "501", 71, _at(self.day, 18), _at(self.day, 19)
        )

        self.assertEqual(warning.result, ScheduleConflictResult.WARNING)
        self.assertEqual(warning.conflicts[0]["type"], "SCHEDULE_ASSIGNMENT")
        self.assertEqual(warning.source_availability, ProviderStatus.OK)
        self.assertEqual(passed.result, ScheduleConflictResult.PASS)

    def test_enrollment_fails_before_seat_deduction_on_hard_conflict(self):
        leave_type = HrLeaveType.objects.create(
            tenant_id=71, code="PERSONAL", name="Personal"
        )
        HrLeaveRequest.objects.create(
            tenant_id=71,
            staff_master_id=501,
            leave_type=leave_type,
            start_at=self.day,
            end_at=self.day,
            requested_amount=1,
            status="APPROVED",
        )
        offering = HrLearningOffering.objects.create(
            tenant_id=71,
            program_version_id=1,
            offering_no="OFFER-71",
            delivery_mode="ONSITE",
            start_at=_at(self.day, 9),
            end_at=_at(self.day, 11),
            capacity=1,
            lifecycle_status="OPEN",
        )

        with self.assertRaises(ValueError) as raised:
            EnrollmentService.enroll(offering, 501, 71)

        self.assertIn("SCHEDULE_CONFLICT", str(raised.exception))
        offering.refresh_from_db()
        self.assertEqual(offering.capacity, 1)
