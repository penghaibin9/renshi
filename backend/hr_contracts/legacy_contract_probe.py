"""HR07 对 payroll.Contract 的恢复期只读探针。

目标是先把真实 legacy 合同事实和字段映射看清楚，再恢复 HR07 Authority 模型。
本模块不注册 Django app、不创建 migration、不写 payroll.Contract。
"""

from __future__ import annotations


LEGACY_CONTRACT_FIELD_MAP = {
    "contract_name": "agreement_title",
    "employee_id_id": "legacy_employee_id",
    "contract_start_date": "effective_from",
    "contract_end_date": "effective_to",
    "contract_status": "legacy_status",
    "department_id": "legacy_department_id",
    "job_position_id": "legacy_job_position_id",
    "job_role_id": "legacy_job_role_id",
    "shift_id": "legacy_shift_id",
    "work_type_id": "legacy_work_type_id",
    "contract_document": "legacy_document_ref",
}


def _legacy_contract_model():
    """Resolve the retired payroll model only when a recovery probe is used."""
    from payroll.models.models import Contract

    return Contract


class LegacyContractProbe:
    """只读盘点 payroll.Contract，所有查询显式 tenant scope。"""

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = tenant_id

    def inventory(self) -> dict:
        Contract = _legacy_contract_model()
        scoped = Contract.objects.filter(
            employee_id__employee_work_info__company_id_id=self.tenant_id
        )
        return {
            "tenantId": self.tenant_id,
            "total": scoped.count(),
            "draft": scoped.filter(contract_status="draft").count(),
            "active": scoped.filter(contract_status="active").count(),
            "expired": scoped.filter(contract_status="expired").count(),
            "terminated": scoped.filter(contract_status="terminated").count(),
            "authority": False,
            "source": "legacy.payroll.Contract",
        }

    def list_snapshots(self, *, limit: int = 200) -> list[dict]:
        """返回恢复核验需要的最小字段，不包含 wage/pay-frequency 等薪酬 Authority。"""
        Contract = _legacy_contract_model()
        safe_limit = max(1, min(int(limit), 1000))
        rows = Contract.objects.filter(
            employee_id__employee_work_info__company_id_id=self.tenant_id
        ).order_by("id").values(
            "id",
            "contract_name",
            "employee_id_id",
            "contract_start_date",
            "contract_end_date",
            "contract_status",
            "department_id",
            "job_position_id",
            "job_role_id",
            "shift_id",
            "work_type_id",
            "contract_document",
        )[:safe_limit]
        return [
            {
                "legacyContractId": row["id"],
                "source": "legacy.payroll.Contract",
                "authority": False,
                "fields": {
                    target: row.get(source)
                    for source, target in LEGACY_CONTRACT_FIELD_MAP.items()
                },
            }
            for row in rows
        ]
