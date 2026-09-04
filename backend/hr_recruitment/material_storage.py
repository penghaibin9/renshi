"""Private, tenant-partitioned storage for HR04 application materials."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename


ALLOWED_MATERIAL_TYPES = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg", "image/jpg"},
    ".jpeg": {"image/jpeg", "image/jpg"},
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    },
}


class MaterialStorageError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 422):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _storage_prefix(*, tenant_id: int, application_id) -> str:
    return f"protected/hr04/{int(tenant_id)}/{application_id}/"


def _validated_storage_key(storage_key: str, *, tenant_id: int, application_id) -> str:
    prefix = _storage_prefix(tenant_id=tenant_id, application_id=application_id)
    key = str(storage_key or "")
    parts = key.split("/")
    if (
        not key.startswith(prefix)
        or key.startswith(("/", "\\"))
        or "\\" in key
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise MaterialStorageError(
            "MATERIAL_STORAGE_INVALID", "材料存储位置无效", status=500
        )
    return key


def _sha256(upload) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks(chunk_size=64 * 1024):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def store_application_material(upload, *, tenant_id: int, application_id) -> dict:
    """Validate and store one uploaded material; never trust client file metadata."""
    if upload is None:
        raise MaterialStorageError("MATERIAL_FILE_REQUIRED", "请选择需要上传的材料")
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        upload, "_malware_scan_complete", False
    ):
        raise MaterialStorageError(
            "MALWARE_SCAN_REQUIRED",
            "材料尚未通过安全检查",
            status=503,
        )

    size = int(getattr(upload, "size", 0) or 0)
    max_bytes = int(
        getattr(settings, "HR04_APPLICATION_MATERIAL_MAX_BYTES", 20 * 1024 * 1024)
    )
    if size <= 0:
        raise MaterialStorageError("MATERIAL_FILE_EMPTY", "材料文件不能为空")
    if size > max_bytes:
        raise MaterialStorageError(
            "MATERIAL_FILE_TOO_LARGE",
            f"单个材料不能超过 {max_bytes // (1024 * 1024)} MiB",
            status=413,
        )

    original_name = get_valid_filename(Path(str(getattr(upload, "name", ""))).name)
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_MATERIAL_TYPES:
        raise MaterialStorageError(
            "MATERIAL_FILE_TYPE_INVALID",
            "材料仅支持 PDF、图片、Word 或 Excel 文件",
        )
    content_type = (
        str(getattr(upload, "content_type", "") or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if content_type not in ALLOWED_MATERIAL_TYPES[suffix]:
        raise MaterialStorageError(
            "MATERIAL_FILE_TYPE_MISMATCH",
            "材料扩展名与内容类型不一致",
        )

    prefix = _storage_prefix(tenant_id=tenant_id, application_id=application_id)
    sha256 = _sha256(upload)
    storage_key = default_storage.save(f"{prefix}{uuid.uuid4().hex}{suffix}", upload)
    try:
        storage_key = _validated_storage_key(
            storage_key,
            tenant_id=tenant_id,
            application_id=application_id,
        )
    except MaterialStorageError:
        default_storage.delete(storage_key)
        raise
    return {
        "file_name": (original_name or f"material{suffix}")[-250:],
        "file_path": storage_key,
        "sha256": sha256,
        "mime_type": content_type,
        "file_size_bytes": size,
    }


def delete_application_material(storage_key: str, *, tenant_id: int, application_id) -> None:
    """Delete only a key inside the exact tenant/application partition."""
    key = _validated_storage_key(
        storage_key,
        tenant_id=tenant_id,
        application_id=application_id,
    )
    if default_storage.exists(key):
        default_storage.delete(key)


def open_application_material(storage_key: str, *, tenant_id: int, application_id):
    """Open one exact tenant/application key without ever exposing a media URL."""
    key = _validated_storage_key(
        storage_key,
        tenant_id=tenant_id,
        application_id=application_id,
    )
    if not default_storage.exists(key):
        raise MaterialStorageError("MATERIAL_FILE_NOT_FOUND", "材料文件不存在", status=404)
    return default_storage.open(key, "rb")
