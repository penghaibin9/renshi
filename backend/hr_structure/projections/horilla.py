"""
hr_structure/projections/horilla.py

HorillaStructureProjectionService —— Legacy 单向投影（总册 30 节）。

权威单向投影到 Horilla legacy（Department/JobPosition），禁止反向覆盖（INV-11）。
- 幂等：projection_hash 相同则跳过；
- 失败可重试，不自动改 mode；
- Authority 切换后 legacy 写入口返回 HR02_LEGACY_WRITE_DISABLED；
- 所有 legacy 读写必须显式 tenant scope，映射异常 fail-closed。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django.utils import timezone

from hr_structure.models import (
    HrLegacyObjectLink,
    HrOrganization,
    HrOrganizationVersion,
    HrPosition,
)


class LegacyProjectionError(Exception):
    pass


def _legacy_department_model():
    from base.models import Department

    return Department


def _legacy_job_position_model():
    from base.models import JobPosition

    return JobPosition


def _legacy_work_info_model():
    from employee.models import EmployeeWorkInformation

    return EmployeeWorkInformation


class HorillaStructureProjectionService:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise LegacyProjectionError("HR02_TENANT_REQUIRED")
        self.tenant_id = tenant_id

    def _hash(self, payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

    def _assert_version_in_tenant(self, version: HrOrganizationVersion) -> None:
        version_tenant_id = getattr(version, "tenant_id", None)
        org = getattr(version, "organization_id", None)
        org_tenant_id = getattr(org, "tenant_id", None)
        if version_tenant_id != self.tenant_id or org_tenant_id != self.tenant_id:
            raise LegacyProjectionError("HR02_CROSS_TENANT_AUTHORITY_OBJECT")

    def _assert_position_in_tenant(self, position: HrPosition) -> None:
        org = getattr(position, "organization_id", None)
        catalog_version = getattr(position, "post_catalog_version_id", None)
        if (
            getattr(position, "tenant_id", None) != self.tenant_id
            or getattr(org, "tenant_id", None) != self.tenant_id
            or getattr(catalog_version, "tenant_id", None) != self.tenant_id
        ):
            raise LegacyProjectionError("HR02_CROSS_TENANT_POSITION")

    def project_organization(self, version: HrOrganizationVersion) -> HrLegacyObjectLink:
        """权威组织 → Horilla Department 投影（单向，幂等，tenant fail-closed）。"""
        self._assert_version_in_tenant(version)

        link = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            domain_entity_type="organization",
            domain_entity_id=str(version.organization_id_id),
            legacy_app="base",
            legacy_model="department",
        ).first()

        payload = {
            "name": version.name,
            "dimension": version.organization_id.org_dimension,
        }
        payload_hash = self._hash(payload)

        if link and link.projection_hash == payload_hash:
            return link  # 幂等：无变化

        legacy_pk = link.legacy_pk if link else None
        if legacy_pk:
            # 关键：不能只按 PK 取 Department，否则坏映射可能更新别的学校数据。
            dept = _legacy_department_model().objects.filter(
                id=int(legacy_pk),
                company_id=self.tenant_id,
            ).first()
            if dept is None:
                raise LegacyProjectionError("HR02_LEGACY_LINK_TENANT_MISMATCH")
        else:
            dept = _legacy_department_model().objects.create(department=version.name)
            # Department.company_id 是 M2M；新投影必须立刻绑定当前 tenant，
            # 禁止生成“无学校归属”的全局 legacy 部门。
            dept.company_id.add(self.tenant_id)

        dept.department = version.name
        dept.save(update_fields=["department"])

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

    def project_position(self, position: HrPosition) -> HrLegacyObjectLink:
        """权威岗位 → Horilla JobPosition 投影，要求组织先完成 tenant-safe Department 映射。"""
        self._assert_position_in_tenant(position)

        org_link = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            domain_entity_type="organization",
            domain_entity_id=str(position.organization_id_id),
            legacy_app="base",
            legacy_model="department",
            link_status="MAPPED",
        ).first()
        if org_link is None or not org_link.legacy_pk:
            raise LegacyProjectionError("HR02_POSITION_ORG_LEGACY_LINK_REQUIRED")

        try:
            legacy_department_id = int(org_link.legacy_pk)
        except (TypeError, ValueError) as exc:
            raise LegacyProjectionError("HR02_POSITION_ORG_LEGACY_LINK_INVALID") from exc

        department = _legacy_department_model().objects.filter(
            id=legacy_department_id,
            company_id=self.tenant_id,
        ).first()
        if department is None:
            raise LegacyProjectionError("HR02_POSITION_ORG_LEGACY_TENANT_MISMATCH")

        link = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            domain_entity_type="position",
            domain_entity_id=str(position.id),
            legacy_app="base",
            legacy_model="jobposition",
        ).first()

        payload = {
            "positionCode": position.position_code,
            "name": position.post_catalog_version_id.name,
            "organizationId": str(position.organization_id_id),
            "lifecycleStatus": position.lifecycle_status,
        }
        payload_hash = self._hash(payload)
        if link and link.projection_hash == payload_hash:
            return link

        if link and link.legacy_pk:
            try:
                legacy_position_id = int(link.legacy_pk)
            except (TypeError, ValueError) as exc:
                raise LegacyProjectionError("HR02_POSITION_LEGACY_LINK_INVALID") from exc
            legacy_position = _legacy_job_position_model().objects.filter(
                id=legacy_position_id,
                company_id=self.tenant_id,
            ).first()
            if legacy_position is None:
                raise LegacyProjectionError("HR02_POSITION_LEGACY_TENANT_MISMATCH")
            legacy_position.job_position = position.post_catalog_version_id.name
            legacy_position.department_id = department
            legacy_position.save(update_fields=["job_position", "department_id"])
        else:
            legacy_position = _legacy_job_position_model().objects.create(
                job_position=position.post_catalog_version_id.name,
                department_id=department,
            )
            # JobPosition.company_id 同样是 M2M；新投影必须立即绑定学校。
            legacy_position.company_id.add(self.tenant_id)

        if link is None:
            return HrLegacyObjectLink.objects.create(
                tenant_id=self.tenant_id,
                domain_entity_type="position",
                domain_entity_id=str(position.id),
                legacy_app="base",
                legacy_model="jobposition",
                legacy_pk=str(legacy_position.id),
                link_status="MAPPED",
                projection_hash=payload_hash,
                last_projected_at=timezone.now(),
            )

        link.projection_hash = payload_hash
        link.last_projected_at = timezone.now()
        link.save(update_fields=["projection_hash", "last_projected_at"])
        return link

    def create_root_from_company(self, company) -> HrOrganization:
        """Company → HrOrganization(SCHOOL) 根（M1，总册 31.2）。幂等且 tenant 一致。"""
        if getattr(company, "id", None) != self.tenant_id:
            raise LegacyProjectionError("HR02_CROSS_TENANT_COMPANY")

        link = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            domain_entity_type="root",
            legacy_app="base",
            legacy_model="company",
            legacy_pk=str(company.id),
        ).first()
        if link:
            org = HrOrganization.objects.filter(
                id=link.domain_entity_id,
                tenant_id=self.tenant_id,
            ).first()
            if org is None:
                raise LegacyProjectionError("HR02_ROOT_LINK_TENANT_MISMATCH")
            return org

        org = HrOrganization.objects.create(
            tenant_id=self.tenant_id,
            stable_code=f"SCH{company.id}",
            org_dimension="ADMIN",
            created_by="migration-m1",
        )
        HrOrganizationVersion.objects.create(
            organization_id=org,
            tenant_id=self.tenant_id,
            name=company.company,
            org_type=HrOrganizationVersion.OrgType.SCHOOL,
            validity_from=timezone.localdate(),
            status=HrOrganizationVersion.Status.EFFECTIVE,
            created_by="migration-m1",
        )
        HrLegacyObjectLink.objects.create(
            tenant_id=self.tenant_id,
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
        active_depts = _legacy_department_model().objects.filter(
            company_id=self.tenant_id,
            is_active=True,
        ).count()
        active_job_positions = _legacy_job_position_model().objects.filter(
            company_id=self.tenant_id,
            is_active=True,
        ).count()
        mapped_depts = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            legacy_app="base",
            legacy_model="department",
            link_status="MAPPED",
        ).count()
        mapped_job_positions = HrLegacyObjectLink.objects.filter(
            tenant_id=self.tenant_id,
            legacy_app="base",
            legacy_model="jobposition",
            link_status="MAPPED",
        ).count()
        # Employee current org mapping（EmployeeWorkInformation.department → HR02 org）
        # 必须显式 company/tenant 过滤，禁止依赖 Horilla request thread-local manager。
        unmapped_employees = _legacy_work_info_model().objects.filter(
            company_id_id=self.tenant_id,
            employee_id__is_active=True,
        ).filter(department_id__isnull=True).count()

        return {
            "tenantId": self.tenant_id,
            "activeLegacyDepartments": active_depts,
            "mappedOrganizations": mapped_depts,
            "activeLegacyJobPositions": active_job_positions,
            "mappedJobPositions": mapped_job_positions,
            "unmappedOrgEmployees": unmapped_employees,
            "generatedAt": timezone.now().isoformat(),
        }
