"""
hr10_development/services/enrollment_service.py

报名与审批服务。
- 报名并发：先 occupy_seat → create enrollment
- 候选转正：release_seat → find waitlisted → create confirmed
- Self-approval detection
"""

from django.db import transaction

from hr10_development.constants import EnrollmentStatus, SeatStatus, DevelopmentErrorCode
from hr10_development.models.enrollment import HrLearningEnrollment
from hr10_development.models.offering import HrLearningOffering
from hr10_development.services.offering_service import OfferingService


class EnrollmentService:
    """报名服务。"""

    @staticmethod
    @transaction.atomic
    def enroll(offering: HrLearningOffering, staff_master_id: int, tenant_id: int) -> HrLearningEnrollment:
        """报名——原子操作：先占名额再建 enrollment。"""
        ok = OfferingService.occupy_seat(offering)
        if not ok:
            raise ValueError(DevelopmentErrorCode.OFFERING_CAPACITY_FULL)

        enrollment = HrLearningEnrollment.objects.create(
            tenant_id=tenant_id,
            offering_id=offering.id,
            staff_master_id=staff_master_id,
            enrollment_status=EnrollmentStatus.CONFIRMED,
            seat_status=SeatStatus.CONFIRMED,
        )
        return enrollment

    @staticmethod
    @transaction.atomic
    def waitlist(offering: HrLearningOffering, staff_master_id: int, tenant_id: int) -> HrLearningEnrollment:
        """进入候补。"""
        ok = OfferingService.occupy_waitlist(offering)
        if not ok:
            raise ValueError(DevelopmentErrorCode.WAITLIST_FULL)

        enrollment = HrLearningEnrollment.objects.create(
            tenant_id=tenant_id,
            offering_id=offering.id,
            staff_master_id=staff_master_id,
            enrollment_status=EnrollmentStatus.WAITLISTED,
            seat_status=SeatStatus.WAITLISTED,
        )
        return enrollment

    @staticmethod
    @transaction.atomic
    def cancel_enrollment(enrollment: HrLearningEnrollment, offering: HrLearningOffering):
        """取消报名→释放名额→触发候补转正。"""
        enrollment.enrollment_status = EnrollmentStatus.CANCELLED
        enrollment.save(update_fields=["enrollment_status", "updated_at"])

        # 释放名额
        OfferingService.release_seat(offering)

        # 候补第一个转正
        next_waitlisted = (
            HrLearningEnrollment.objects
            .filter(
                offering_id=offering.id,
                enrollment_status=EnrollmentStatus.WAITLISTED,
            )
            .order_by("created_at")
            .first()
        )
        if next_waitlisted:
            next_waitlisted.enrollment_status = EnrollmentStatus.CONFIRMED
            next_waitlisted.seat_status = SeatStatus.CONFIRMED
            next_waitlisted.save(update_fields=["enrollment_status", "seat_status", "updated_at"])

    @staticmethod
    @transaction.atomic
    def mark_no_show(enrollment: HrLearningEnrollment, offering: HrLearningOffering) -> HrLearningEnrollment:
        """标记未出席——释放名额 + 触发候补转正 + 记录 NO_SHOW 状态。"""
        enrollment.enrollment_status = EnrollmentStatus.NO_SHOW
        enrollment.save(update_fields=["enrollment_status", "updated_at"])

        OfferingService.release_seat(offering)

        next_waitlisted = (
            HrLearningEnrollment.objects
            .filter(offering_id=offering.id, enrollment_status=EnrollmentStatus.WAITLISTED)
            .order_by("created_at").first()
        )
        if next_waitlisted:
            next_waitlisted.enrollment_status = EnrollmentStatus.CONFIRMED
            next_waitlisted.seat_status = SeatStatus.CONFIRMED
            next_waitlisted.save(update_fields=["enrollment_status", "seat_status", "updated_at"])
        return enrollment


def check_self_approval(applicant_id: int, approver_id: int) -> bool:
    """禁止自审批：applicant == final_approver。"""
    return applicant_id == approver_id
