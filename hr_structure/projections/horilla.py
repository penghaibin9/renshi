"""
hr_structure/projections/horilla.py

HorillaStructureProjectionService —— Legacy 单向投影（总册 30 节）。

权威单向投影到 Horilla legacy（Department/JobPosition），禁止反向覆盖（INV-11）。
- 幂等：projection_hash 相同则跳过；
- 失败可重试，不自动改 mode；
- Authority 切换后 legacy 写入口返回 HR02_LEGACY_WRITE_DISABLED。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.utils import timezone

from hr_structure.models import HrLegacyObjectLink, HrOrganization, HrOrganizationVersion


class LegacyProjectionError(Exception):
    pass


class HorillaStructureProjectionService:
    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id

    def _hash(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def project_organization(self, version: HrOrganizationVersion) -> HrLegacyObjectLink:
        """权威组织 → Horilla Department 投影（单向，幂等）。"""
        from base.models import Department

        link = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            domain_entity_type="organization",
            domain_entity_id=str(version.organization_id_id),
            legacy_app="base",
            legacy_model="department",
        ).first()

        payload = {"name": version.name, "dimension": version.organization_id.org_dimension}
        payload_hash = self._hash(payload)

        if link and link.projection_hash == payload_hash:
            return link  # 幂等：无变化

        # 投影到 Horilla Department（若已存在 legacy 映射则更新，否则新建）
        legacy_pk = link.legacy_pk if link else None
        if legacy_pk:
            dept = Department.objects.filter(id=int(legacy_pk)).first()
        else:
            dept = None
        if dept is None:
            dept = Department.objects.create(department=version.name)
        else:
            dept.department = version.name
            dept.save()

        if link is None:
            link = HrLegacyObjectLink.objects.create(
                tenant_id=self.tenant_id,
                domain_entity_type="organization",
                domain_entity_id=str(version.organization_id_id),
                legacy_app="base",
                legacy_model="department",
                legacy_pk=str(dept.id),
                link_status="MAPPED",
                projection_hash=payload_hash,
                last_projected_at=timezone.now(),
            )
        else:
            link.projection_hash = payload_hash
            link.last_projected_at = timezone.now()
            link.save(update_fields=["projection_hash", "last_projected_at"])
        return link

    def create_root_from_company(self, company) -> HrOrganization:
        """Company → HrOrganization(SCHOOL) 根（M1，总册 31.2）。幂等。"""
        link = HrLegacyObjectLink.objects.filter(
            tenant_id=company.id,
            domain_entity_type="root",
            legacy_app="base",
            legacy_model="company",
            legacy_pk=str(company.id),
        ).first()
        if link:
            return HrOrganization.objects.filter(id=link.domain_entity_id).first()

        org = HrOrganization.objects.create(
            tenant_id=company.id,
            stable_code=f"SCH{company.id}",
            org_dimension="ADMIN",
            created_by="migration-m1",
        )
        HrOrganizationVersion.objects.create(
            organization_id=org,
            tenant_id=company.id,
            name=company.company,
            org_type=HrOrganizationVersion.OrgType.SCHOOL,
            validity_from=date.today(),
            status=HrOrganizationVersion.Status.EFFECTIVE,
            created_by="migration-m1",
        )
        HrLegacyObjectLink.objects.create(
            tenant_id=company.id,
            domain_entity_type="root",
            domain_entity_id=str(org.id),
            legacy_app="base",
            legacy_model="company",
            legacy_pk=str(company.id),
            link_status="MAPPED",
            projection_hash=self._hash({"company": company.company}),
        )
        return org

    def reconcile_report(self) -> dict:
        """对账（总册 30.2 DUAL_READ_COMPARE 维度），严格按 tenant 隔离。"""
        from base.models import Department
        from employee.models import EmployeeWorkInformation

        active_depts = Department.objects.filter(
            company_id=self.tenant_id,
            is_active=True,
        ).count()
        mapped_depts = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            legacy_model="department",
            link_status="MAPPED",
        ).count()
        # Employee current org mapping（EmployeeWorkInformation.department → HR02 org）
        # 必须显式 company/tenant 过滤，禁止依赖 Horilla request thread-local manager。
        unmapped_employees = EmployeeWorkInformation.objects.filter(
            company_id_id=self.tenant_id,
            employee_id__is_active=True,
        ).filter(department_id__isnull=True).count()

        return {
            "tenantId": self.tenant_id,
            "activeLegacyDepartments": active_depts,
            "mappedOrganizations": mapped_depts,
            "unmappedOrgEmployees": unmapped_employees,
            "generatedAt": timezone.now().isoformat(),
        }
