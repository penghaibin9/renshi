"""Validated, storage-backed evidence uploads for HR16 workflows."""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename


MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
ALLOWED_EVIDENCE_EXTENSIONS = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx", ".txt"}
)
ALLOWED_EVIDENCE_CONTENT_TYPES = {
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
    ".txt": {"text/plain"},
}


class EvidenceUploadError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(message)


def is_private_evidence_ref(reference: str) -> bool:
    return str(reference or "").startswith("storage://protected/hr16/")


def _validated_storage_name(
    reference: str,
    *,
    tenant_id: int,
    allowed_categories: set[str] | frozenset[str] | tuple[str, ...],
) -> str:
    prefix = "storage://"
    value = str(reference or "")
    if not value.startswith(prefix):
        raise EvidenceUploadError(
            "EVIDENCE_FILE_NOT_AVAILABLE", "该凭证不是系统内可下载文件", status=404
        )
    storage_name = value[len(prefix) :]
    parts = storage_name.split("/")
    expected_root = ["protected", "hr16", str(int(tenant_id))]
    if (
        storage_name.startswith(("/", "\\"))
        or "\\" in storage_name
        or any(part in {"", ".", ".."} for part in parts)
        or parts[:3] != expected_root
        or len(parts) != 5
        or parts[3] not in set(allowed_categories)
    ):
        raise EvidenceUploadError(
            "EVIDENCE_STORAGE_INVALID", "凭证存储引用无效", status=404
        )
    return storage_name


def save_evidence(upload, *, tenant_id: int, category: str) -> tuple[str, str]:
    if upload is None:
        raise EvidenceUploadError("EVIDENCE_FILE_REQUIRED", "请选择需要上传的凭证文件")
    size = int(getattr(upload, "size", 0) or 0)
    if size <= 0:
        raise EvidenceUploadError("EVIDENCE_FILE_EMPTY", "凭证文件不能为空")
    if size > MAX_EVIDENCE_BYTES:
        raise EvidenceUploadError("EVIDENCE_FILE_TOO_LARGE", "凭证文件不能超过 10 MiB")
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        upload, "_malware_scan_complete", False
    ):
        raise EvidenceUploadError(
            "MALWARE_SCAN_REQUIRED", "凭证尚未通过安全检查", status=503
        )

    original_name = get_valid_filename(Path(str(getattr(upload, "name", ""))).name)
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EVIDENCE_EXTENSIONS:
        raise EvidenceUploadError(
            "EVIDENCE_FILE_TYPE_INVALID",
            "仅支持 PDF、图片、Word、Excel 或 TXT 凭证",
        )
    content_type = (
        str(getattr(upload, "content_type", "") or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if content_type not in ALLOWED_EVIDENCE_CONTENT_TYPES[suffix]:
        raise EvidenceUploadError(
            "EVIDENCE_FILE_TYPE_MISMATCH", "凭证扩展名与内容类型不一致"
        )
    category = str(category or "").strip()
    if category not in {"handover", "archive-package", "archive-receipt", "archive-return"}:
        raise EvidenceUploadError("EVIDENCE_CATEGORY_INVALID", "凭证分类无效")
    safe_name = original_name[-120:] or f"evidence{suffix}"
    storage_name = default_storage.save(
        f"protected/hr16/{int(tenant_id)}/{category}/{uuid.uuid4().hex}-{safe_name}",
        upload,
    )
    reference = f"storage://{storage_name}"
    if len(reference) > 256:
        default_storage.delete(storage_name)
        raise EvidenceUploadError("EVIDENCE_REFERENCE_TOO_LONG", "凭证存储引用过长")
    return reference, storage_name


def open_evidence(
    reference: str,
    *,
    tenant_id: int,
    allowed_categories: set[str] | frozenset[str] | tuple[str, ...],
):
    """Open one exact tenant/category partition without exposing its storage key."""

    storage_name = _validated_storage_name(
        reference,
        tenant_id=tenant_id,
        allowed_categories=allowed_categories,
    )
    if not default_storage.exists(storage_name):
        raise EvidenceUploadError(
            "EVIDENCE_FILE_NOT_FOUND", "凭证文件不存在", status=404
        )
    basename = Path(storage_name).name
    filename = basename.split("-", 1)[1] if "-" in basename else basename
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        stream = default_storage.open(storage_name, "rb")
    except OSError as exc:
        raise EvidenceUploadError(
            "EVIDENCE_FILE_NOT_FOUND", "凭证文件暂时无法读取", status=404
        ) from exc
    return stream, filename, content_type, hashlib.sha256(
        storage_name.encode("utf-8")
    ).hexdigest()


def delete_evidence(storage_name: str) -> None:
    if storage_name:
        default_storage.delete(storage_name)
