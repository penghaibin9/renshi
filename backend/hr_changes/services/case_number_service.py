"""
hr_changes/services/case_number_service.py —— case_no 生成（并发安全）。

对齐总册 §9 + hr_staff HrStaffNumberSequence 模式：
- 序列行行锁 + (tenant_id, prefix) 唯一；O(1) 分配；
- 已使用编号默认不回收；规则变更不重写历史编号。
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from hr_changes.models import HrPersonnelChangeCase
from hr_staff.models import HrStaffNumberSequence


class CaseNumberConflict(Exception):
    code = "CASE_NUMBER_CONFLICT"


class CaseNumberService:
    """tenant-scoped 案件号生成：HRCHG-YYYY-NNNNNN。"""

    PREFIX = "HRCHG"

    def __init__(self, tenant_id: int, width: int = 6):
        self.tenant_id = tenant_id
        self.width = max(4, width)

    def next_no(self) -> str:
        year = timezone.localdate().year
        seq, _ = HrStaffNumberSequence.objects.select_for_update().get_or_create(
            tenant_id=self.tenant_id,
            prefix=self.PREFIX,
            defaults={"next_value": 1},
        )
        # 跨年重置
        from django.db.models import F

        value = seq.next_value
        seq.next_value = F("next_value") + 1
        seq.save(update_fields=["next_value", "updated_at"])
        seq.refresh_from_db(fields=["next_value"])
        return f"{self.PREFIX}-{year}-{value:0{self.width}d}"

    @transaction.atomic
    def allocate(self) -> str:
        return self.next_no()


def case_no_available(case_no: str, tenant_id: int) -> bool:
    return not HrPersonnelChangeCase.objects.filter(
        tenant_id=tenant_id, case_no=case_no
    ).exists()
