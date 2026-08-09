"""
hr10_development/services/offering_service.py

班次名额并发控制服务。
"""

from django.db import transaction
from django.db.models import F

from hr10_development.constants import EnrollmentStatus, SeatStatus
from hr10_development.models.offering import HrLearningOffering


class OfferingService:
    """班次名额与候补管理。"""

    @staticmethod
    @transaction.atomic
    def occupy_seat(offering: HrLearningOffering) -> bool:
        """占用名额。并发安全——UPDATE + WHERE 条件。"""
        updated = (
            HrLearningOffering.objects
            .filter(
                id=offering.id,
                version=offering.version,
            )
            .update(
                capacity=F("capacity") - 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        offering.refresh_from_db()
        # 名额用完后自动关闭
        if offering.capacity <= 0 and offering.waitlist_capacity <= 0:
            from hr10_development.constants import OfferingStatus
            HrLearningOffering.objects.filter(id=offering.id).update(
                lifecycle_status=OfferingStatus.CLOSED,
            )
        return True

    @staticmethod
    @transaction.atomic
    def release_seat(offering: HrLearningOffering) -> bool:
        """释放名额。"""
        updated = (
            HrLearningOffering.objects
            .filter(
                id=offering.id,
                version=offering.version,
            )
            .update(
                capacity=F("capacity") + 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        offering.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def occupy_waitlist(offering: HrLearningOffering) -> bool:
        """占用候补名额。"""
        if offering.waitlist_capacity <= 0:
            return False
        updated = (
            HrLearningOffering.objects
            .filter(
                id=offering.id,
                version=offering.version,
                waitlist_capacity__gt=0,
            )
            .update(
                waitlist_capacity=F("waitlist_capacity") - 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        offering.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def promote_waitlist(offering: HrLearningOffering) -> bool:
        """候补转正——先加名额再占。"""
        updated = (
            HrLearningOffering.objects
            .filter(
                id=offering.id,
                version=offering.version,
            )
            .update(
                waitlist_capacity=F("waitlist_capacity") + 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            return False
        offering.refresh_from_db()
        return OfferingService.occupy_seat(offering.offering)
