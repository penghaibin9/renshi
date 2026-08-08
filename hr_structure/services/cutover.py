"""
hr_structure/services/cutover.py

Hr02CutoverService —— Authority 切换（总册 30.4 / 50.8）。

- 按 tenant 级 feature flag：LEGACY_STRUCTURE_ONLY / DUAL_READ_COMPARE / HR02_AUTHORITY；
- 切换必须写 operator/old_mode/new_mode/reason/reconcile_report_id；
- 禁止全局 boolean 一把切；
- 回滚只允许回 DUAL_READ_COMPARE（受控），不允许 silent fallback legacy。
"""

from __future__ import annotations

from django.db import transaction

from hr_structure.models import Hr02AuthorityCutover


class Hr02CutoverService:
    def __init__(self, operator: str = ""):
        self.operator = operator

    def get_mode(self, tenant_id) -> str:
        record = Hr02AuthorityCutover.objects.filter(tenant_id=tenant_id).first()
        return record.mode if record else Hr02AuthorityCutover.Mode.LEGACY_STRUCTURE_ONLY

    @transaction.atomic
    def set_mode(self, tenant_id, new_mode, *, reason="", reconcile_report_id="") -> Hr02AuthorityCutover:
        valid = (
            Hr02AuthorityCutover.Mode.LEGACY_STRUCTURE_ONLY,
            Hr02AuthorityCutover.Mode.DUAL_READ_COMPARE,
            Hr02AuthorityCutover.Mode.HR02_AUTHORITY,
        )
        if new_mode not in valid:
            raise ValueError(f"非法 mode: {new_mode}")
        record, _ = Hr02AuthorityCutover.objects.get_or_create(
            tenant_id=tenant_id,
            defaults={"mode": Hr02AuthorityCutover.Mode.LEGACY_STRUCTURE_ONLY},
        )
        record.old_mode = record.mode
        record.mode = new_mode
        record.operator = self.operator
        record.reason = reason
        record.reconcile_report_id = reconcile_report_id
        record.save()
        return record
