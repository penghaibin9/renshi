"""
hr10_development/services/enrollment_service.py

报名与审批服务。
- 报名并发：先 occupy_seat → create enrollment
- 候选转正：release_seat → find waitlisted → promote_waitlist
- Self-approval detection
"""

from django.db import transaction
from django.utils import timezone

from hr10_development.constants import (
    DevelopmentErrorCode,
    EnrollmentStatus,
    ScheduleConflictResult,
    SeatStatus,
)
from hr10_development.models.enrollment import HrLearningEnrollment
from hr10_development.models.offering import HrLearningOffering
from hr10_development.providers.base import ProviderStatus
from hr10_development.providers.time_provider import Hr11TimeConflictProvider
from hr10_development.services.offering_service import OfferingService


class EnrollmentService:
    """报名服务。"""

    @staticmethod
    def _assert_schedule_eligible(
        offering: HrLearningOffering,
        staff_master_id: int,
        tenant_id: int,
        *,
        conflict_provider=None,
    ):
        if int(offering.tenant_id) != int(tenant_id):
            raise ValueError(DevelopmentErrorCode.NOT_FOUND)
        if offering.start_at is None or offering.end_at is None:
            raise ValueError(DevelopmentErrorCode.SCHEDULE_SOURCE_UNAVAILABLE)

        provider = conflict_provider or Hr11TimeConflictProvider()
        result = provider.check_conflict(
            str(staff_master_id),
            tenant_id,
            offering.start_at,
            offering.end_at,
        )
        if (
            result.source_availability != ProviderStatus.OK
            or result.result == ScheduleConflictResult.SOURCE_UNAVAILABLE
        ):
            raise ValueError(DevelopmentErrorCode.SCHEDULE_SOURCE_UNAVAILABLE)
        if result.result == ScheduleConflictResult.BLOCKED:
            raise ValueError(DevelopmentErrorCode.SCHEDULE_CONFLICT)
        return result

    @staticmethod
    @transaction.atomic
    def enroll(
        offering: HrLearningOffering,
        staff_master_id: int,
        tenant_id: int,
        *,
        conflict_provider=None,
    ) -> HrLearningEnrollment:
        """报名——先通过 HR11 权威冲突检查，再原子占名额并建 enrollment。"""
        offering = HrLearningOffering.objects.select_for_update().filter(
            id=offering.id,
            tenant_id=tenant_id,
        ).first()
        if offering is None:
            raise ValueError(DevelopmentErrorCode.NOT_FOUND)
        from hr10_development.constants import OfferingStatus
        from hr_staff.models import HrStaffMaster

        if offering.lifecycle_status != OfferingStatus.OPEN:
            raise ValueError(DevelopmentErrorCode.OFFERING_NOT_OPEN)
        now = timezone.now()
        if (offering.enrollment_open_at and now < offering.enrollment_open_at) or (
            offering.enrollment_close_at and now >= offering.enrollment_close_at
        ):
            raise ValueError(DevelopmentErrorCode.OFFERING_NOT_OPEN)
        if not HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            legacy_employee_id=staff_master_id,
        ).exists():
            raise ValueError(DevelopmentErrorCode.NOT_FOUND)
        if HrLearningEnrollment.objects.filter(
            tenant_id=tenant_id,
            offering_id=offering.id,
            staff_master_id=staff_master_id,
        ).exists():
            raise ValueError(DevelopmentErrorCode.DUPLICATE_ENROLLMENT)
        EnrollmentService._assert_schedule_eligible(
            offering,
            staff_master_id,
            tenant_id,
            conflict_provider=conflict_provider,
        )
        ok = OfferingService.occupy_seat(offering)
        if not ok:
            raise ValueError(DevelopmentErrorCode.OFFERING_CAPACITY_FULL)

        return HrLearningEnrollment.objects.create(
            tenant_id=tenant_id,
            offering_id=offering.id,
            staff_master_id=staff_master_id,
            enrollment_status=EnrollmentStatus.CONFIRMED,
            seat_status=SeatStatus.CONFIRMED,
        )

    @staticmethod
    @transaction.atomic
    def waitlist(
        offering: HrLearningOffering,
        staff_master_id: int,
        tenant_id: int,
    ) -> HrLearningEnrollment:
        """进入候补。"""
        offering = HrLearningOffering.objects.select_for_update().filter(
            id=offering.id,
            tenant_id=tenant_id,
        ).first()
        if offering is None:
            raise ValueError(DevelopmentErrorCode.NOT_FOUND)
        from hr10_development.constants import OfferingStatus
        from hr_staff.models import HrStaffMaster

        if offering.lifecycle_status != OfferingStatus.WAITLIST_OPEN or offering.capacity > 0:
            raise ValueError(DevelopmentErrorCode.OFFERING_NOT_OPEN)
        if not HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            legacy_employee_id=staff_master_id,
        ).exists():
            raise ValueError(DevelopmentErrorCode.NOT_FOUND)
        if HrLearningEnrollment.objects.filter(
            tenant_id=tenant_id,
            offering_id=offering.id,
            staff_master_id=staff_master_id,
        ).exists():
            raise ValueError(DevelopmentErrorCode.DUPLICATE_ENROLLMENT)
        ok = OfferingService.occupy_waitlist(offering)
        if not ok:
            raise ValueError(DevelopmentErrorCode.WAITLIST_FULL)

        return HrLearningEnrollment.objects.create(
            tenant_id=tenant_id,
            offering_id=offering.id,
            staff_master_id=staff_master_id,
            enrollment_status=EnrollmentStatus.WAITLISTED,
            seat_status=SeatStatus.WAITLISTED,
        )

    @staticmethod
    def _promote_first_waitlisted(offering: HrLearningOffering) -> None:
        next_waitlisted = (
            HrLearningEnrollment.objects.filter(
                tenant_id=offering.tenant_id,
                offering_id=offering.id,
                enrollment_status=EnrollmentStatus.WAITLISTED,
            )
            .order_by("created_at")
            .first()
        )
        if next_waitlisted is None:
            return

        # release_seat 已经先释放了一个正式席位。候补转正必须同时：
        # 1) 归还候补槽位；2) 重新占用该正式席位；否则 capacity 会虚增。
        if not OfferingService.promote_waitlist(offering):
            return

        next_waitlisted.enrollment_status = EnrollmentStatus.CONFIRMED
        next_waitlisted.seat_status = SeatStatus.CONFIRMED
        next_waitlisted.save(
            update_fields=["enrollment_status", "seat_status", "updated_at"]
        )

    @staticmethod
    def _lock_enrollment_and_offering(enrollment, offering):
        """Resolve caller objects to one current, tenant-bound locked pair."""
        tenant_id = getattr(enrollment, "tenant_id", None)
        locked_enrollment = (
            HrLearningEnrollment.objects.select_for_update()
            .filter(
                id=getattr(enrollment, "id", None),
                tenant_id=tenant_id,
                offering_id=getattr(offering, "id", None),
            )
            .first()
        )
        locked_offering = (
            HrLearningOffering.objects.select_for_update()
            .filter(
                id=getattr(offering, "id", None),
                tenant_id=tenant_id,
            )
            .first()
        )
        if locked_enrollment is None or locked_offering is None:
            raise ValueError(DevelopmentErrorCode.NOT_FOUND)
        return locked_enrollment, locked_offering

    @staticmethod
    @transaction.atomic
    def cancel_enrollment(
        enrollment: HrLearningEnrollment,
        offering: HrLearningOffering,
    ) -> HrLearningEnrollment:
        """幂等取消报名，并只释放该报名实际占用的名额类型。"""
        enrollment, offering = EnrollmentService._lock_enrollment_and_offering(
            enrollment, offering
        )
        if enrollment.enrollment_status == EnrollmentStatus.CANCELLED:
            return enrollment

        previous_status = enrollment.enrollment_status
        if previous_status not in {
            EnrollmentStatus.CONFIRMED,
            EnrollmentStatus.WAITLISTED,
        }:
            raise ValueError(DevelopmentErrorCode.REQUEST_ALREADY_FINAL)

        enrollment.enrollment_status = EnrollmentStatus.CANCELLED
        enrollment.seat_status = ""
        enrollment.save(
            update_fields=["enrollment_status", "seat_status", "updated_at"]
        )

        if previous_status == EnrollmentStatus.WAITLISTED:
            if not OfferingService.release_waitlist(offering):
                raise ValueError(DevelopmentErrorCode.VERSION_CONFLICT)
        else:
            if not OfferingService.release_seat(offering):
                raise ValueError(DevelopmentErrorCode.VERSION_CONFLICT)
            EnrollmentService._promote_first_waitlisted(offering)
        return enrollment

    @staticmethod
    @transaction.atomic
    def mark_no_show(
        enrollment: HrLearningEnrollment,
        offering: HrLearningOffering,
    ) -> HrLearningEnrollment:
        """标记未出席——释放名额 + 触发候补转正 + 记录 NO_SHOW 状态。"""
        enrollment, offering = EnrollmentService._lock_enrollment_and_offering(
            enrollment, offering
        )
        if enrollment.enrollment_status == EnrollmentStatus.NO_SHOW:
            return enrollment
        if enrollment.enrollment_status != EnrollmentStatus.CONFIRMED:
            raise ValueError(DevelopmentErrorCode.REQUEST_ALREADY_FINAL)

        enrollment.enrollment_status = EnrollmentStatus.NO_SHOW
        enrollment.seat_status = ""
        enrollment.save(
            update_fields=["enrollment_status", "seat_status", "updated_at"]
        )

        if not OfferingService.release_seat(offering):
            raise ValueError(DevelopmentErrorCode.VERSION_CONFLICT)
        EnrollmentService._promote_first_waitlisted(offering)
        return enrollment


def check_self_approval(applicant_id: int, approver_id: int) -> bool:
    """禁止自审批：applicant == final_approver。"""
    return applicant_id == approver_id
