"""
hr_staff/selectors/materials.py —— 材料元数据查询（S8，只读）。

只回元数据（title/category/sensitivity/current version/sha256/过期），不回文件正文；
敏感材料详情按权限裁剪。
"""

from __future__ import annotations

from hr_staff.context import HrStaffRequestContext
from hr_staff.models import HrStaffMaterial, HrStaffMaterialVersion
from hr_staff.policies.scope_policy import StaffNotFound


class MaterialSelector:
    def __init__(self, context: HrStaffRequestContext):
        self.context = context
        self.tenant_id = context.tenant_id

    def _deny_check(self, staff_id):
        """P1-5：读路径强制 data scope（tenant + scope + fail-closed）。"""
        from hr_staff.policies.scope_policy import ScopeEnforcer

        return ScopeEnforcer(self.context).get_staff_or_deny(staff_id)

    def list_materials(self, staff_id) -> dict:
        self._deny_check(staff_id)  # P1-5
        materials = list(
            HrStaffMaterial.objects.filter(tenant_id=self.tenant_id, staff_id=staff_id)
            .order_by("-updated_at")
        )
        # P2-N+1：批量取 CURRENT 版本（一次查询）
        current_versions = {
            v.material_id_id: v
            for v in HrStaffMaterialVersion.objects.filter(
                tenant_id=self.tenant_id,
                material_id__in=[m.id for m in materials],
                status="CURRENT",
            )
        }
        items = []
        for m in materials:
            current = current_versions.get(m.id)
            items.append(
                {
                    "id": str(m.id),
                    "categoryCode": m.category_code,
                    "title": m.title,
                    "sensitivityLevel": m.sensitivity_level,
                    "verificationStatus": m.verification_status,
                    "currentVersionNo": current.version_no if current else None,
                    "originalFilename": current.original_filename if current else None,
                    "mimeType": current.mime_type if current else None,
                    "sizeBytes": current.size_bytes if current else 0,
                    "sha256": current.sha256 if current else "",
                    "expiryDate": current.expiry_date.isoformat() if current and current.expiry_date else None,
                    "relatedFactType": m.related_fact_type,
                }
            )
        return {"items": items}

    def version_history(self, staff_id, material_id) -> dict:
        self._deny_check(staff_id)  # P1-5
        versions = (
            HrStaffMaterialVersion.objects.filter(
                tenant_id=self.tenant_id,
                material_id_id=material_id,
                material_id__staff_id=staff_id,
            )
            .order_by("-version_no")
        )
        return {
            "materialId": str(material_id),
            "versions": [
                {
                    "id": str(v.id),
                    "versionNo": v.version_no,
                    "status": v.status,
                    "sha256": v.sha256,
                    "sizeBytes": v.size_bytes,
                    "uploadedAt": v.uploaded_at.isoformat(),
                    "verifiedAt": v.verified_at.isoformat() if v.verified_at else None,
                    "replacedByVersionId": (
                        str(v.replaced_by_version_id) if v.replaced_by_version_id else None
                    ),
                }
                for v in versions
            ],
        }
