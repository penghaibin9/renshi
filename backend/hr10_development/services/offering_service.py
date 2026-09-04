"""
hr10_development/services/offering_service.py

班次名额并发控制服务。
"""

from django.db import transaction
from django.db.models import F

from hr10_development.models.offering import HrLearningOffering


class OfferingService:
    """班次名额与候补管理。"""

    @staticmethod
    @transaction.atomic
    def occupy_seat(offering: HrLearningOffering) -> bool:
        """占用名额。并发安全——仅在剩余名额 > 0 且版本匹配时原子扣减。"""
        updated = (
            HrLearningOffering.objects.filter(
                id=offering.id,
                version=offering.version,
                capacity__gt=0,
            ).update(
                capacity=F("capacity") - 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            # 可能是名额已满，也可能是并发版本已推进；两种情况都不能继续扣减。
            offering.refresh_from_db()
            return False

        offering.refresh_from_db()
        from hr10_development.constants import OfferingStatus

        if offering.capacity <= 0:
            next_status = (
                OfferingStatus.WAITLIST_OPEN
                if offering.waitlist_capacity > 0
                else OfferingStatus.CLOSED
            )
            HrLearningOffering.objects.filter(id=offering.id).update(
                lifecycle_status=next_status,
            )
            offering.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def release_seat(offering: HrLearningOffering) -> bool:
        """释放一个正式名额。"""
        updated = (
            HrLearningOffering.objects.filter(
                id=offering.id,
                version=offering.version,
            ).update(
                capacity=F("capacity") + 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            offering.refresh_from_db()
            return False
        from hr10_development.constants import OfferingStatus

        HrLearningOffering.objects.filter(id=offering.id).update(
            lifecycle_status=OfferingStatus.OPEN,
        )
        offering.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def occupy_waitlist(offering: HrLearningOffering) -> bool:
        """占用一个候补名额。"""
        updated = (
            HrLearningOffering.objects.filter(
                id=offering.id,
                version=offering.version,
                waitlist_capacity__gt=0,
            ).update(
                waitlist_capacity=F("waitlist_capacity") - 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            offering.refresh_from_db()
            return False
        if offering.waitlist_capacity <= 0:
            from hr10_development.constants import OfferingStatus

            HrLearningOffering.objects.filter(id=offering.id).update(
                lifecycle_status=OfferingStatus.CLOSED,
            )
            offering.refresh_from_db()
        offering.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def release_waitlist(offering: HrLearningOffering) -> bool:
        """释放一个候补槽位，不改变正式席位数量。"""
        updated = HrLearningOffering.objects.filter(
            id=offering.id,
            version=offering.version,
        ).update(
            waitlist_capacity=F("waitlist_capacity") + 1,
            version=F("version") + 1,
        )
        if not updated:
            offering.refresh_from_db()
            return False

        offering.refresh_from_db()
        from hr10_development.constants import OfferingStatus

        next_status = (
            OfferingStatus.OPEN
            if offering.capacity > 0
            else OfferingStatus.WAITLIST_OPEN
        )
        HrLearningOffering.objects.filter(id=offering.id).update(
            lifecycle_status=next_status,
        )
        offering.refresh_from_db()
        return True

    @staticmethod
    @transaction.atomic
    def promote_waitlist(offering: HrLearningOffering) -> bool:
        """候补转正：释放一个候补槽位，并占用一个已释放的正式名额。"""
        updated = (
            HrLearningOffering.objects.filter(
                id=offering.id,
                version=offering.version,
                capacity__gt=0,
            ).update(
                waitlist_capacity=F("waitlist_capacity") + 1,
                version=F("version") + 1,
            )
        )
        if not updated:
            offering.refresh_from_db()
            return False

        offering.refresh_from_db()
        return OfferingService.occupy_seat(offering)
