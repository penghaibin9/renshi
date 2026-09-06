"""
hr_staff/services/staff_master_service.py —— staff_no 生成 + StaffMaster 创建（总册 §8.2）。

规则：
- staff_no tenant scoped；前缀/长度可配置（读 EmployeeGeneralSetting.badge_id_prefix 兼容 legacy）；
- 已使用编号默认不回收；规则变更不重写历史编号；
- 同一 tenant 同一 person 默认一份 StaffMaster（canonical），重复创建抛错；
- legacy_employee_id 只作映射。
"""

from __future__ import annotations

import re
from typing import Optional

from django.db import transaction

from hr_staff.models import HrStaffMaster


def _legacy_general_setting_model():
    from employee.models import EmployeeGeneralSetting

    return EmployeeGeneralSetting

class StaffNoConflict(Exception):
    code = "STAFF_NO_CONFLICT"


class DuplicateStaffMaster(Exception):
    code = "DUPLICATE_STAFF_MASTER"


class CrossTenantReference(Exception):
    code = "CROSS_TENANT_REFERENCE"


class StaffNumberService:
    """tenant-scoped 工号生成（P1-j：序列行锁，O(1) 分配，无截断）。"""

    def __init__(self, prefix: str = "", width: int = 6):
        self.prefix = prefix.strip() if prefix else ""
        self.width = max(1, width)

    @staticmethod
    def _legacy_prefix(tenant_id: int) -> str:
        """Read only the selected school's legacy prefix; database failures must surface."""
        from django.apps import apps

        if not apps.is_installed("employee"):
            return "T"
        setting = _legacy_general_setting_model().objects.filter(
            company_id_id=tenant_id
        ).first()
        if setting and setting.badge_id_prefix:
            value = setting.badge_id_prefix.strip()
            if value:
                return value
        return "T"

    @staticmethod
    def _max_existing_numeric(tenant_id: int, prefix: str) -> int:
        """首次初始化：扫描现有工号取同前缀最大数值后缀（仅一次，之后走序列）。"""
        from hr_staff.models import HrStaffMaster

        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        max_no = 0
        qs = HrStaffMaster.objects.filter(tenant_id=tenant_id).values_list("staff_no", flat=True)
        for no in qs.iterator(chunk_size=2000):
            m = pattern.match(no or "")
            if m:
                try:
                    max_no = max(max_no, int(m.group(1)))
                except ValueError:
                    continue
        return max_no

    def next_staff_no(self, tenant_id: int) -> str:
        """
        分配下一个工号：锁 (tenant_id, prefix) 序列行，O(1) 分配。
        首次创建序列时以现有最大工号+1 初始化（兼容既有数据）。
        DB (tenant, staff_no) 唯一 + 序列行锁保证并发安全。
        """
        from hr_staff.models import HrStaffNumberSequence

        prefix = self.prefix or self._legacy_prefix(tenant_id)
        with transaction.atomic():
            seq, created = HrStaffNumberSequence.objects.get_or_create(
                tenant_id=tenant_id,
                prefix=prefix,
                defaults={"next_value": self._max_existing_numeric(tenant_id, prefix) + 1},
            )
            seq = HrStaffNumberSequence.objects.select_for_update().get(pk=seq.pk)
            if created:
                # 并发首次创建时另一进程可能已初始化；校正为 max(现有, 序列)
                seq.next_value = max(
                    seq.next_value, self._max_existing_numeric(tenant_id, prefix) + 1
                )
            candidate = f"{prefix}{seq.next_value:0{self.width}d}"
            seq.next_value += 1
            seq.save(update_fields=["next_value", "updated_at"])
        return candidate


class StaffMasterService:
    def __init__(self, staff_number_service: Optional[StaffNumberService] = None):
        self.staff_number_service = staff_number_service or StaffNumberService()

    @transaction.atomic
    def create_staff(
        self,
        *,
        tenant_id: int,
        person_id,
        staff_category_code: str = "TEACHER",
        staff_no: Optional[str] = None,
        legacy_employee_id: Optional[int] = None,
        source: str = "HR_ENTERED",
        audit_actor_user_id: Optional[int] = None,
    ) -> HrStaffMaster:
        # N6/P1-6：person 必须属于当前 tenant（支持实例或 UUID/str）
        from hr_staff.models import HrPerson

        if isinstance(person_id, HrPerson):
            person = person_id
        else:
            person = HrPerson.objects.filter(tenant_id=tenant_id, id=person_id).first()
        if person is None or person.tenant_id != tenant_id:
            raise CrossTenantReference(f"person 不属于当前学校（tenant={tenant_id}）")

        if staff_no is None:
            staff_no = self.staff_number_service.next_staff_no(tenant_id)

        if HrStaffMaster.objects.filter(tenant_id=tenant_id, staff_no=staff_no).exists():
            raise StaffNoConflict(f"staff_no {staff_no} already exists in tenant {tenant_id}")

        if HrStaffMaster.objects.filter(tenant_id=tenant_id, person_id=person_id).exists():
            raise DuplicateStaffMaster(
                "person already has a canonical StaffMaster in this tenant"
            )

        staff = HrStaffMaster.objects.create(
            tenant_id=tenant_id,
            person_id=person,
            staff_no=staff_no,
            staff_category_code=staff_category_code,
            legacy_employee_id=legacy_employee_id,
            source=source,
        )
        # P1-f：StaffMaster 创建必审计（§28.2）
        from hr_staff.services.audit_service import write_audit_event

        write_audit_event(
            tenant_id=tenant_id,
            action="StaffMasterCreated",
            actor_user_id=audit_actor_user_id,
            staff_id=staff.id,
            reason=f"staff_no={staff_no} source={source}",
        )
        # outbox
        from hr_staff.services.outbox_service import staff_master_created

        staff_master_created(tenant_id, staff.id, staff_no, source)
        return staff

    def get_by_legacy_employee(self, tenant_id: int, legacy_employee_id: int) -> Optional[HrStaffMaster]:
        return HrStaffMaster.objects.filter(
            tenant_id=tenant_id, legacy_employee_id=legacy_employee_id
        ).first()

    # ------------------------------------------------------------------
    # 人员类别变更（HR06 调用；新增 domain 方法，不改变历史模型语义）
    # ------------------------------------------------------------------
    @transaction.atomic
    def update_staff_category(
        self,
        *,
        tenant_id: int,
        staff_id,
        staff_category_code: str,
        source_business_type: str = "",
        source_business_id: str = "",
        reason_code: str = "",
    ) -> HrStaffMaster:
        staff = HrStaffMaster.objects.filter(tenant_id=tenant_id, id=staff_id).first()
        if staff is None:
            raise StaffNoConflict(f"staff not found in tenant {tenant_id}")
        if staff.staff_category_code == staff_category_code:
            return staff
        staff.staff_category_code = staff_category_code
        staff.version += 1
        staff.save(update_fields=["staff_category_code", "version", "updated_at"])
        from hr_staff.services.audit_service import write_audit_event

        write_audit_event(
            tenant_id=tenant_id,
            action="StaffCategoryChanged",
            staff_id=staff.id,
            business_type=source_business_type,
            business_id=source_business_id,
            reason=reason_code,
        )
        return staff
