"""Canonical owned, private HR03 evidence references for business authorities."""
import uuid
import hashlib

class EvidenceReferenceError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.status = code, status
        super().__init__(message)

def evidence_snapshot(tenant_id, staff_id, version_id, *, lock=False):
    """Accept only a real, owned, private HR03 file version, not a made-up URL."""
    from django.core.files.storage import default_storage
    from hr_staff.models import HrStaffMaterialVersion
    query = HrStaffMaterialVersion.objects
    if lock:
        query = query.select_for_update()
    version = query.select_related("material_id").filter(
        tenant_id=tenant_id, id=uuid.UUID(str(version_id)),
        material_id__tenant_id=tenant_id, material_id__staff_id_id=staff_id,
    ).first()
    if version is None:
        raise EvidenceReferenceError("FLEX_EVIDENCE_NOT_FOUND", "材料不属于本校本人，或材料不存在", 404)
    prefix = f"protected/hr03/{int(tenant_id)}/{str(staff_id).replace('-', '').lower()}/"
    if (version.status not in {"CURRENT", "REPLACED"} or not version.storage_file_id.startswith(prefix)
            or ".." in version.storage_file_id.split("/") or version.size_bytes <= 0
            or len(version.sha256) != 64 or any(c not in "0123456789abcdef" for c in version.sha256.lower())):
        raise EvidenceReferenceError("FLEX_EVIDENCE_UNVERIFIABLE", "材料未形成有效私有文件版本，不能作为审批依据")
    if not default_storage.exists(version.storage_file_id):
        raise EvidenceReferenceError("EVIDENCE_FILE_MISSING", "材料元数据存在，但实际文件不可读取，不能作为审批依据", 409)
    from hr_staff.services.material_file_service import MAX_MATERIAL_BYTES
    if version.size_bytes > MAX_MATERIAL_BYTES:
        raise EvidenceReferenceError("EVIDENCE_SIZE_INVALID", "材料超出可核验大小", 409)
    digest, size = hashlib.sha256(), 0
    try:
        with default_storage.open(version.storage_file_id, "rb") as stream:
            while True:
                chunk = stream.read(128 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > version.size_bytes or size > MAX_MATERIAL_BYTES:
                    raise EvidenceReferenceError("EVIDENCE_BYTES_CHANGED", "实际材料内容与提交回执不一致", 409)
                digest.update(chunk)
    except OSError as exc:
        raise EvidenceReferenceError("EVIDENCE_STORAGE_UNAVAILABLE", "材料存储暂不可读取，未报告审批成功", 503) from exc
    if size != version.size_bytes or digest.hexdigest() != version.sha256.lower():
        raise EvidenceReferenceError("EVIDENCE_BYTES_CHANGED", "实际材料内容与提交回执不一致", 409)
    return {
        "materialId": str(version.material_id_id),
        "versionId": str(version.id),
        "sha256": version.sha256.lower(),
        "sizeBytes": version.size_bytes,
        "categoryCode": version.material_id.category_code,
        "verificationStatus": version.material_id.verification_status,
        "versionStatus": version.status,
        "verifiedBy": version.verified_by,
        "verifiedAt": version.verified_at.isoformat() if version.verified_at else None,
    }

