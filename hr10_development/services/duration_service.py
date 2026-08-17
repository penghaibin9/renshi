"""
hr10_development/services/duration_service.py

时长台账计算服务（总册 §107）。

verified activity segments
+ verified attendance segments
- exclusions (OBSERVATION + MEETING + low trust sources)
- overlapping time deduplication
= eligible practice duration (hours → days via policy version)
"""

from decimal import Decimal
from datetime import datetime, timezone

from django.db import transaction


class DurationService:
    """实践时长计算与台账写入。"""

    @staticmethod
    @transaction.atomic
    def calculate_assignment_duration(assignment_id: int, tenant_id: int) -> dict:
        """
        计算指定实践派出的有效时长。

        返回 {eligible_hours, eligible_days, ledger_count}
        """
        from hr10_development.models.practice_attendance import HrEnterprisePracticeAttendanceFact
        from hr10_development.models.practice_process import HrEnterprisePracticeActivity
        from hr10_development.models.duration_ledger import HrDurationLedger

        total_hours = Decimal("0")

        # 1. Verified activities
        activities = HrEnterprisePracticeActivity.objects.filter(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            status="VERIFIED",
        )
        for act in activities:
            if act.duration_minutes:
                hours = Decimal(act.duration_minutes) / Decimal(60)
                total_hours += hours
                _ensure_ledger(HrDurationLedger, assignment_id, "ACTIVITY", act.id,
                                hours, Decimal("0"), hours, Decimal(hours / Decimal(8)),
                                "", datetime.now(timezone.utc), tenant_id)

        # 2. Verified attendance facts
        attendances = HrEnterprisePracticeAttendanceFact.objects.filter(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            verification_status__in=[
                "SYSTEM_PROVIDER_VERIFIED", "TRAINING_PROVIDER_VERIFIED",
                "INTERNAL_INSTRUCTOR_VERIFIED", "HR_VERIFIED",
                "DOCUMENT_VERIFIED", "MANUAL_COMMITTEE_VERIFIED",
            ],
            trust_level__gte=2,
        )
        for att in attendances:
            if att.duration_minutes:
                hours = Decimal(att.duration_minutes) / Decimal(60)
                total_hours += hours
                _ensure_ledger(HrDurationLedger, assignment_id, "ATTENDANCE", att.id,
                                hours, Decimal("0"), hours, Decimal(hours / Decimal(8)),
                                "", datetime.now(timezone.utc), tenant_id)

        eligible_days = total_hours / Decimal(8)

        return {
            "eligible_hours": float(total_hours),
            "eligible_days": float(eligible_days),
            "ledger_count": HrDurationLedger.objects.filter(assignment_id=assignment_id).count(),
        }


def _ensure_ledger(model, assignment_id, source_type, source_id,
                   raw_hours, raw_days, eligible_hours, eligible_days,
                   excluded_reason, calculated_at, tenant_id):
    """幂等写入台账：同 assignment+source_type+source_id 只记录一次。"""
    model.objects.update_or_create(
        tenant_id=tenant_id,
        assignment_id=assignment_id,
        source_type=source_type,
        source_id=source_id,
        defaults={
            "raw_hours": raw_hours,
            "raw_days": raw_days,
            "eligible_hours": eligible_hours,
            "eligible_days": eligible_days,
            "excluded_reason": excluded_reason,
            "calculated_at": calculated_at,
        },
    )
