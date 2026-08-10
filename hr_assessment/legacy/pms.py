"""HR12 对 Horilla PMS Objective/EmployeeObjective 的迁移期只读 adapter。

旧 PMS 目标可以作为考核设计/历史证据来源，但不得直接成为 HR12 正式考核结果：
- 读取显式 tenant scope；
- 保留旧状态和进度，不偷偷翻译为 HR12 评分/等级；
- adapter 只读，不反向写 PMS；
- 所有返回都标记 authority=False。
"""

from __future__ import annotations


class PmsLegacyObjectiveAdapter:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = tenant_id

    def list_employee_objectives(self, *, legacy_employee_id: int, limit: int = 500) -> list[dict]:
        from pms.models import EmployeeObjective

        safe_limit = max(1, min(int(limit), 1000))
        rows = (
            EmployeeObjective.objects.filter(
                employee_id_id=legacy_employee_id,
                employee_id__employee_work_info__company_id_id=self.tenant_id,
            )
            .order_by("id")
            .values(
                "id",
                "objective_id_id",
                "objective",
                "objective_description",
                "start_date",
                "end_date",
                "status",
                "progress_percentage",
                "archive",
            )[:safe_limit]
        )
        return [
            {
                **row,
                "source": "legacy.pms.EmployeeObjective",
                "legacyStatus": row.get("status"),
                "legacyProgressPercentage": row.get("progress_percentage"),
                "factKind": "LEGACY_OBJECTIVE_PROGRESS",
                "authority": False,
            }
            for row in rows
        ]
