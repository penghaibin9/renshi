"""
hr_time/services/schedule_service.py

S3 排班服务：

- 创建排班前做重叠检查（同人员同时间区间不允许两套生效排班）；
- as-of 查询人员当日排班（含 ScheduleException overlay）；
- 排班冲突分级（HARD/SOFT/INFO）基础实现（§50）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from hr_time.models.schedule import HrScheduleAssignment, HrScheduleException


@dataclass(frozen=True)
class ScheduleConflict:
    level: str  # HARD_CONFLICT / SOFT_CONFLICT / INFO / SOURCE_UNAVAILABLE
    reasons: list = field(default_factory=list)
    blocking_refs: list = field(default_factory=list)


class ScheduleService:
    @staticmethod
    @transaction.atomic
    def create_assignment(assignment: HrScheduleAssignment) -> HrScheduleAssignment:
        """创建排班，先做重叠检查（fail-closed：重叠即拒绝，不静默合并）。"""
        base_qs = HrScheduleAssignment.objects.filter(
            tenant_id=assignment.tenant_id,
            staff_master_id=assignment.staff_master_id,
        ).exclude(pk=assignment.pk)

        # 有效区间 [effective_from, effective_to) 半开区间
        overlaps = base_qs.filter(
            Q(effective_from__lt=assignment.effective_to or date.max)
            & (
                Q(effective_to__isnull=True)
                | Q(effective_to__gt=assignment.effective_from)
            )
        )
        if overlaps.exists():
            raise ValidationError(
                "排班时间段重叠，禁止重复排班（同一人员同一时间区间只能有一套生效排班）",
                code="SCHEDULE_OVERLAP",
            )
        assignment.clean()
        assignment.save()
        return assignment

    @staticmethod
    def get_assignment_as_of(
        *, tenant_id: int, staff_master_id: int, day: date
    ) -> Optional[HrScheduleAssignment]:
        """as-of 查询人员在指定日期的生效排班。"""
        return (
            HrScheduleAssignment.objects.filter(
                tenant_id=tenant_id,
                staff_master_id=staff_master_id,
                effective_from__lte=day,
            )
            .filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=day)
            )
            .order_by("-effective_from", "-version")
            .first()
        )

    @staticmethod
    def get_exception_as_of(
        *, tenant_id: int, schedule_assignment_id: int, day: date
    ) -> Optional[HrScheduleException]:
        """as-of 查询当日排班例外。"""
        return (
            HrScheduleException.objects.filter(
                tenant_id=tenant_id,
                schedule_assignment_id=schedule_assignment_id,
                date_from__lte=day,
                date_to__gte=day,
            )
            .order_by("-date_from")
            .first()
        )
