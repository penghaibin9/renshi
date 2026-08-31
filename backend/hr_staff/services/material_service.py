"""
hr_staff/services/material_service.py —— 材料档案服务（S8）。

安全合同：
- 下载必须验证 tenant + staff data scope + material permission + sensitivity + purpose + status + audit；
- 下载走短时效一次性 ticket（不返回 /media/ 裸 URL）；
- 版本链：旧版本不可无痕覆盖；替换/作废记录完整；
- 材料跨 tenant 永远拒绝。
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_staff.constants import (
    MaterialVersionStatus,
    SensitivityLevel,
    VerificationStatus,
)
from hr_staff.models import (
    HrMaterialDownloadTicket,
    HrStaffMaterial,
    HrStaffMaterialVersion,
)
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.common import resolve_staff


class MaterialAccessDenied(Exception):
    code = "MATERIAL_ACCESS_DENIED"


class MaterialVersionConflict(Exception):
    code = "MATERIAL_VERSION_CONFLICT"


class MaterialService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # 创建材料 + 首个版本
    # ------------------------------------------------------------------
    @transaction.atomic
    def create_material(
        self,
        *,
        staff_id,
        category_code: str,
        title: str,
        sensitivity_level: str = SensitivityLevel.RESTRICTED_HR,
        storage_file_id: str = "",
        original_filename: str = "",
        mime_type: str = "",
        size_bytes: int = 0,
        sha256: str = "",
        issue_date=None,
        expiry_date=None,
        legacy_document_id: Optional[int] = None,
    ) -> HrStaffMaterial:
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6 跨租户防线
        material = HrStaffMaterial.objects.create(
            tenant_id=self.tenant_id,
            staff_id=staff,
            category_code=category_code,
            title=title,
            sensitivity_level=sensitivity_level,
        )
        version = HrStaffMaterialVersion.objects.create(
            tenant_id=self.tenant_id,
            material_id=material,
            version_no=1,
            storage_file_id=storage_file_id,
            legacy_document_id=legacy_document_id,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            issue_date=issue_date,
            expiry_date=expiry_date,
            uploaded_by=self.actor_user_id,
            status=MaterialVersionStatus.CURRENT,
        )
        material.current_version_id = version.id
        material.save(update_fields=["current_version_id"])
        write_audit_event(
            tenant_id=self.tenant_id,
            action="MaterialUploaded",
            actor_user_id=self.actor_user_id,
            staff_id=staff_id.id,
            business_type="MATERIAL",
            business_id=str(material.id),
            reason=f"v{version.version_no}",
        )
        return material

    # ------------------------------------------------------------------
    # 新增版本（旧版本不可无痕覆盖）
    # ------------------------------------------------------------------
    @transaction.atomic
    def add_version(
        self,
        *,
        material_id,
        storage_file_id: str,
        original_filename: str = "",
        mime_type: str = "",
        size_bytes: int = 0,
        sha256: str = "",
        issue_date=None,
        expiry_date=None,
    ) -> HrStaffMaterialVersion:
        material = (
            HrStaffMaterial.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, id=material_id)
            .first()
        )
        if material is None:
            raise MaterialAccessDenied("MATERIAL_NOT_FOUND")
        # 旧 CURRENT 版本置 REPLACED（保留历史，不覆盖）
        current = HrStaffMaterialVersion.objects.filter(
            tenant_id=self.tenant_id, material_id=material, status=MaterialVersionStatus.CURRENT
        )
        for old in current:
            old.status = MaterialVersionStatus.REPLACED
            old.replaced_by_version_id = None  # 在创建新版本后回填
            old.save(update_fields=["status", "replaced_by_version_id"])

        next_no = (
            HrStaffMaterialVersion.objects.filter(
                tenant_id=self.tenant_id, material_id=material
            ).count()
            + 1
        )
        new_version = HrStaffMaterialVersion.objects.create(
            tenant_id=self.tenant_id,
            material_id=material,
            version_no=next_no,
            storage_file_id=storage_file_id,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            issue_date=issue_date,
            expiry_date=expiry_date,
            uploaded_by=self.actor_user_id,
            status=MaterialVersionStatus.CURRENT,
        )
        # 回填 replaced_by_version_id
        HrStaffMaterialVersion.objects.filter(
            tenant_id=self.tenant_id,
            material_id=material,
            status=MaterialVersionStatus.REPLACED,
            replaced_by_version_id__isnull=True,
        ).update(replaced_by_version_id=new_version.id)
        material.current_version_id = new_version.id
        material.save(update_fields=["current_version_id"])
        write_audit_event(
            tenant_id=self.tenant_id,
            action="MaterialVersionAdded",
            actor_user_id=self.actor_user_id,
            staff_id=material.staff_id_id,
            business_type="MATERIAL",
            business_id=str(material.id),
            reason=f"v{new_version.version_no}",
        )
        return new_version

    # ------------------------------------------------------------------
    # 核验
    # ------------------------------------------------------------------
    @transaction.atomic
    def verify_material(self, *, material_id, staff_id=None) -> HrStaffMaterial:
        material = HrStaffMaterial.objects.filter(
            tenant_id=self.tenant_id, id=material_id
        ).first()
        if material is None:
            raise MaterialAccessDenied("MATERIAL_NOT_FOUND")
        # P2：URL staff 归属校验（与 ticket 路径一致）
        if staff_id is not None and str(material.staff_id_id) != str(staff_id):
            raise MaterialAccessDenied("MATERIAL_ACCESS_DENIED")
        material.verification_status = VerificationStatus.VERIFIED
        material.save(update_fields=["verification_status"])
        version = HrStaffMaterialVersion.objects.filter(
            tenant_id=self.tenant_id, material_id=material, status=MaterialVersionStatus.CURRENT
        ).first()
        if version:
            version.verified_by = self.actor_user_id
            version.verified_at = timezone.now()
            version.save(update_fields=["verified_by", "verified_at"])
        write_audit_event(
            tenant_id=self.tenant_id,
            action="StaffMaterialVerified",
            actor_user_id=self.actor_user_id,
            staff_id=material.staff_id_id,
            business_type="MATERIAL",
            business_id=str(material.id),
        )
        # outbox
        from hr_staff.services.outbox_service import staff_material_verified

        staff_material_verified(self.tenant_id, material.staff_id_id, material.id)
        return material

    # ------------------------------------------------------------------
    # 下载票据（短时效一次性/有限次数；落 DB，跨进程可用）
    # ------------------------------------------------------------------
    def issue_download_ticket(
        self,
        *,
        staff_id,
        material_id,
        version_id=None,
        purpose: str = "",
        permission_ok: bool = False,
        sensitive_ok: bool = False,
        expires_in_seconds: int = 300,
        max_uses: int = 1,
    ) -> dict:
        """签发下载票据（P1-11：归属校验 + DB 票据 + 分级权限）。"""
        staff = resolve_staff(self.tenant_id, staff_id)  # P1-6
        material = HrStaffMaterial.objects.filter(
            tenant_id=self.tenant_id, id=material_id
        ).first()
        if material is None:
            raise MaterialAccessDenied("MATERIAL_NOT_FOUND")
        # P1-11：票据必须归属于 URL 中的 staff
        if material.staff_id_id != staff.id:
            raise MaterialAccessDenied("MATERIAL_ACCESS_DENIED")
        # 敏感材料需要敏感权限（服务层分级检查，视图不得硬编码 ok）
        if material.sensitivity_level in (SensitivityLevel.SENSITIVE, SensitivityLevel.HIGH_SENSITIVE) and not sensitive_ok:
            raise MaterialAccessDenied("MATERIAL_ACCESS_DENIED")
        if not permission_ok:
            raise MaterialAccessDenied("MATERIAL_ACCESS_DENIED")
        if not purpose.strip():
            raise MaterialAccessDenied("PURPOSE_REQUIRED")

        version = None
        if version_id:
            version = HrStaffMaterialVersion.objects.filter(
                tenant_id=self.tenant_id, id=version_id, material_id=material
            ).first()
        else:
            version = HrStaffMaterialVersion.objects.filter(
                tenant_id=self.tenant_id, material_id=material, status=MaterialVersionStatus.CURRENT
            ).first()
        if version is None:
            raise MaterialAccessDenied("MATERIAL_VERSION_NOT_FOUND")

        token = secrets.token_urlsafe(32)
        HrMaterialDownloadTicket.objects.create(
            token=token,
            tenant_id=self.tenant_id,
            staff_id=staff,
            material_id=material,
            version_id=version,
            purpose=purpose,
            issued_by=self.actor_user_id,
            expires_at=timezone.now() + timedelta(seconds=expires_in_seconds),
            max_uses=max_uses,
        )
        write_audit_event(
            tenant_id=self.tenant_id,
            action="MaterialDownloadTicket",
            actor_user_id=self.actor_user_id,
            staff_id=material.staff_id_id,
            business_type="MATERIAL",
            business_id=str(material.id),
            reason=purpose[:500],
        )
        return {
            "ticket": token,
            "expiresAt": (timezone.now() + timedelta(seconds=expires_in_seconds)).isoformat(),
            "maxUses": max_uses,
            "versionNo": version.version_no,
            "originalFilename": version.original_filename,
        }

    @transaction.atomic
    def consume_download_ticket(
        self, token: str, *, expected_staff_id=None, expected_material_id=None
    ) -> dict:
        """消费票据：原子自增（行锁），返回版本文件引用；失效/超次/归属不符 → 拒绝且不烧票。"""
        ticket = (
            HrMaterialDownloadTicket.objects.select_for_update()
            .filter(token=token)
            .first()
        )
        if ticket is None:
            raise MaterialAccessDenied("MATERIAL_TICKET_INVALID")
        if ticket.tenant_id != self.tenant_id:
            raise MaterialAccessDenied("MATERIAL_TICKET_INVALID")
        # N7：归属校验先于消费，避免 URL 不匹配时白白烧票
        if expected_staff_id is not None and str(ticket.staff_id_id) != str(expected_staff_id):
            raise MaterialAccessDenied("MATERIAL_TICKET_INVALID")
        if expected_material_id is not None and str(ticket.material_id_id) != str(expected_material_id):
            raise MaterialAccessDenied("MATERIAL_TICKET_INVALID")
        if timezone.now() > ticket.expires_at:
            raise MaterialAccessDenied("MATERIAL_TICKET_EXPIRED")
        if ticket.uses >= ticket.max_uses:
            raise MaterialAccessDenied("MATERIAL_TICKET_USED_UP")
        ticket.uses += 1
        if ticket.uses >= ticket.max_uses:
            ticket.consumed_at = timezone.now()
        ticket.save(update_fields=["uses", "consumed_at"])
        write_audit_event(
            tenant_id=self.tenant_id,
            action="MaterialDownloaded",
            actor_user_id=self.actor_user_id,
            staff_id=ticket.staff_id_id,
            business_type="MATERIAL",
            business_id=str(ticket.material_id_id),
            reason=ticket.purpose[:500],
        )
        return {
            "materialId": str(ticket.material_id_id),
            "versionId": str(ticket.version_id_id),
            "storageFileId": ticket.version_id.storage_file_id,
            "originalFilename": ticket.version_id.original_filename,
            "mimeType": ticket.version_id.mime_type,
            "sizeBytes": ticket.version_id.size_bytes,
        }
