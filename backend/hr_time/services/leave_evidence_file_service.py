"""Private, tenant-partitioned file storage for HR11 leave evidence."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename


MAX_LEAVE_EVIDENCE_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg", "image/jpg"},
    ".jpeg": {"image/jpeg", "image/jpg"},
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
}


class LeaveEvidenceFileError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _digest(upload) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def store_leave_evidence(upload, *, tenant_id: int, leave_request_id) -> dict:
    if upload is None:
        raise LeaveEvidenceFileError("LEAVE_EVIDENCE_REQUIRED", "请选择证明文件")
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        upload, "_malware_scan_complete", False
    ):
        raise LeaveEvidenceFileError(
            "MALWARE_SCAN_REQUIRED", "证明文件尚未通过安全检查", status=503
        )
    size = int(getattr(upload, "size", 0) or 0)
    if size <= 0:
        raise LeaveEvidenceFileError("INVALID_REQUEST", "证明文件不能为空")
    if size > MAX_LEAVE_EVIDENCE_BYTES:
        raise LeaveEvidenceFileError("INVALID_REQUEST", "证明文件不能超过 10 MiB", status=413)

    original_name = get_valid_filename(Path(str(getattr(upload, "name", ""))).name)
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise LeaveEvidenceFileError(
            "INVALID_REQUEST", "证明文件仅支持 PDF、图片或 Word 文档"
        )
    content_type = str(getattr(upload, "content_type", "") or "").split(";", 1)[0].lower()
    if content_type not in ALLOWED_TYPES[suffix]:
        raise LeaveEvidenceFileError("INVALID_REQUEST", "证明文件扩展名与内容类型不一致")

    document_id = uuid.uuid4().hex
    sha256 = _digest(upload)
    storage_key = (
        f"protected/hr11/{int(tenant_id)}/{leave_request_id}/"
        f"{document_id}{suffix}"
    )
    saved_key = default_storage.save(storage_key, upload)
    return {
        "document_id": document_id,
        "storage_key": saved_key,
        "original_name": (original_name or f"evidence{suffix}")[:255],
        "content_type": content_type[:127],
        "file_size": size,
        "sha256": sha256,
    }


def delete_leave_evidence(storage_key: str) -> None:
    if storage_key and default_storage.exists(storage_key):
        default_storage.delete(storage_key)


def open_leave_evidence(storage_key: str, *, tenant_id: int):
    prefix = f"protected/hr11/{int(tenant_id)}/"
    if not storage_key or not storage_key.startswith(prefix):
        raise LeaveEvidenceFileError("TENANT_SCOPE_VIOLATION", "证明文件存储引用无效", status=404)
    if not default_storage.exists(storage_key):
        raise LeaveEvidenceFileError("LEAVE_EVIDENCE_NOT_FOUND", "证明文件不存在", status=404)
    try:
        return default_storage.open(storage_key, "rb")
    except OSError as exc:
        raise LeaveEvidenceFileError(
            "LEAVE_EVIDENCE_NOT_FOUND", "证明文件暂时无法读取", status=404
        ) from exc
