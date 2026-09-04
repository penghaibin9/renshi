"""Private, tenant-partitioned storage for HR07 contract PDF evidence."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename


class ContractDocumentStorageError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 422):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _prefix(*, tenant_id: int, agreement_id) -> str:
    return f"hr_contracts_private/{int(tenant_id)}/{agreement_id}/"


def _validated_key(storage_key: str, *, tenant_id: int, agreement_id) -> str:
    prefix = _prefix(tenant_id=tenant_id, agreement_id=agreement_id)
    key = str(storage_key or "")
    if (
        not key.startswith(prefix)
        or key.startswith(("/", "\\"))
        or "\\" in key
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_STORAGE_INVALID",
            "合同文档存储位置无效",
            status=500,
        )
    return key


def _digest_and_header(upload) -> tuple[str, bytes]:
    digest = hashlib.sha256()
    header = b""
    upload.seek(0)
    for chunk in upload.chunks(chunk_size=64 * 1024):
        if not header:
            header = bytes(chunk[:8])
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest(), header


def store_contract_document(upload, *, tenant_id: int, agreement_id) -> dict:
    """Validate and store one PDF without trusting the browser's path or MIME."""
    if upload is None:
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_REQUIRED", "请选择需要上传的合同文档"
        )
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        upload, "_malware_scan_complete", False
    ):
        raise ContractDocumentStorageError(
            "MALWARE_SCAN_REQUIRED", "合同文档尚未通过安全检查", status=503
        )

    size = int(getattr(upload, "size", 0) or 0)
    max_bytes = min(
        int(getattr(settings, "MALWARE_SCAN_MAX_BYTES", 50 * 1024 * 1024)),
        20 * 1024 * 1024,
    )
    if size <= 0:
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_EMPTY", "合同文档不能为空"
        )
    if size > max_bytes:
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_TOO_LARGE",
            f"单个合同文档不能超过 {max_bytes // (1024 * 1024)} MiB",
            status=413,
        )

    original_name = get_valid_filename(Path(str(getattr(upload, "name", ""))).name)
    content_type = (
        str(getattr(upload, "content_type", "") or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if Path(original_name).suffix.lower() != ".pdf" or content_type != "application/pdf":
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_TYPE_INVALID", "合同签署文件仅支持 PDF 格式"
        )

    sha256, header = _digest_and_header(upload)
    if not header.startswith(b"%PDF-"):
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_CONTENT_INVALID", "文件内容不是有效的 PDF"
        )

    prefix = _prefix(tenant_id=tenant_id, agreement_id=agreement_id)
    storage_key = default_storage.save(
        f"{prefix}{uuid.uuid4().hex}.pdf", upload
    )
    try:
        storage_key = _validated_key(
            storage_key, tenant_id=tenant_id, agreement_id=agreement_id
        )
    except ContractDocumentStorageError:
        default_storage.delete(storage_key)
        raise
    return {
        "file_path": storage_key,
        "file_name": (original_name or "contract.pdf")[-255:],
        "mime_type": "application/pdf",
        "size_bytes": size,
        "sha256": sha256,
    }


def open_contract_document(storage_key: str, *, tenant_id: int, agreement_id):
    key = _validated_key(
        storage_key, tenant_id=tenant_id, agreement_id=agreement_id
    )
    if not default_storage.exists(key):
        raise ContractDocumentStorageError(
            "CONTRACT_DOCUMENT_NOT_FOUND", "合同文档文件不存在", status=404
        )
    return default_storage.open(key, "rb")


def delete_contract_document(storage_key: str, *, tenant_id: int, agreement_id) -> None:
    key = _validated_key(
        storage_key, tenant_id=tenant_id, agreement_id=agreement_id
    )
    if default_storage.exists(key):
        default_storage.delete(key)
