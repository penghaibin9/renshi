from hr_time.models.close import HrTimeClosePeriod


class PeriodWriteBlocked(Exception):
    pass


def lock_writable_periods(*, tenant_id, start_date, end_date):
    """Serialize formal time writes with close/reopen on every overlapping period."""
    periods = list(
        HrTimeClosePeriod.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        .order_by("start_date", "id")
    )
    blocked = [row for row in periods if row.status in {"PRE_CLOSE", "CLOSED"}]
    if blocked:
        raise PeriodWriteBlocked(
            "期间已预关闭/月结冻结；必须先走独立审批的 Reopen/Correction"
        )
    return periods
