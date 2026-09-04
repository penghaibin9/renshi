"""HR03 personnel material private storage boundary."""

from __future__ import annotations

import hashlib
import os
import uuid

from django.conf import settings
from django.core.files.storage import default_storage

MAX_MATERIAL_BYTES = 50 * 1024 * 1024
ALLOWED_TYPES = {
    ".pdf": (b"%PDF", "application/pdf"),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/msword"),
    ".docx": (b"PK", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/vnd.ms-excel"),
    ".xlsx": (b"PK", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".jpg": (b"\xff\xd8\xff", "image/jpeg"),
    ".jpeg": (b"\xff\xd8\xff", "image/jpeg"),
    ".png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    ".txt": (None, "text/plain"),
}


class StaffMaterialFileError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _staff_segment(staff_id) -> str:
    return str(staff_id).replace("-", "").lower()


def store_staff_material(upload, *, tenant_id: int, staff_id) -> dict:
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        upload, "_malware_scan_complete", False
    ):
        raise StaffMaterialFileError(
            "MALWARE_SCAN_REQUIRED", "材料尚未通过安全检查", status=503
        )
    name = os.path.basename(str(getattr(upload, "name", "") or ""))
    if not name or len(name) > 255:
        raise StaffMaterialFileError("MATERIAL_FILE_INVALID", "文件名无效")
    ext = os.path.splitext(name)[1].lower()
    rule = ALLOWED_TYPES.get(ext)
    if rule is None:
        raise StaffMaterialFileError(
            "MATERIAL_FILE_TYPE_DENIED", "仅允许 PDF、Office、图片和文本材料"
        )
    declared = str(getattr(upload, "content_type", "") or "").split(";", 1)[0].lower()
    accepted = {rule[1]}
    if ext in (".jpg", ".jpeg"):
        accepted.add("image/jpg")
    if declared and declared != "application/octet-stream" and declared not in accepted:
        raise StaffMaterialFileError("MATERIAL_FILE_MIME_MISMATCH", "文件类型与扩展名不一致")
    if int(getattr(upload, "size", 0) or 0) > MAX_MATERIAL_BYTES:
        raise StaffMaterialFileError("MATERIAL_FILE_TOO_LARGE", "文件不得超过 50MB")

    digest = hashlib.sha256()
    head = b""
    size = 0
    for chunk in upload.chunks():
        size += len(chunk)
        if size > MAX_MATERIAL_BYTES:
            raise StaffMaterialFileError("MATERIAL_FILE_TOO_LARGE", "文件不得超过 50MB")
        digest.update(chunk)
        if len(head) < 16:
            head += bytes(chunk[: 16 - len(head)])
    magic = rule[0]
    if magic is not None and not head.startswith(magic):
        raise StaffMaterialFileError("MATERIAL_FILE_CONTENT_MISMATCH", "文件内容与扩展名不一致")
    upload.seek(0)
    key = (
        f"protected/hr03/{int(tenant_id)}/{_staff_segment(staff_id)}/"
        f"{uuid.uuid4().hex}{ext}"
    )
    saved = default_storage.save(key, upload)
    if saved != key:
        default_storage.delete(saved)
        raise StaffMaterialFileError("MATERIAL_STORAGE_COLLISION", "材料存储键冲突", status=503)
    return {
        "storage_file_id": key,
        "original_filename": name,
        "mime_type": rule[1],
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def open_staff_material(storage_key: str, *, tenant_id: int, staff_id):
    key = str(storage_key or "").replace("\\", "/")
    expected = f"protected/hr03/{int(tenant_id)}/{_staff_segment(staff_id)}/"
    if not key.startswith(expected) or key.startswith("/") or ".." in key.split("/"):
        raise StaffMaterialFileError(
            "MATERIAL_STORAGE_SCOPE_INVALID", "材料存储范围无效", status=403
        )
    if not default_storage.exists(key):
        raise StaffMaterialFileError("MATERIAL_FILE_NOT_FOUND", "材料文件不存在", status=404)
    return default_storage.open(key, "rb")


def delete_staff_material(storage_key: str, *, tenant_id: int, staff_id) -> None:
    try:
        stream = open_staff_material(storage_key, tenant_id=tenant_id, staff_id=staff_id)
        stream.close()
    except StaffMaterialFileError:
        return
    default_storage.delete(storage_key)
