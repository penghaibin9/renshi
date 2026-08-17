"""
hr_onboarding/services/file_service.py

文件安全（总册 §41 / 05 §12.7）：
- 私有存储 + tenant+case 隔离子路径，不用 /media/ 裸 URL 长期暴露；
- SHA-256 + MIME/扩展名/大小校验；
- 下载走短时效一次性 ticket（00 §34）。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import timedelta
from typing import Optional

from django.core.cache import cache
from django.core.files.storage import default_storage

TICKET_TTL_SECONDS = 60 * 5  # 5 分钟短时效


def compute_sha256(uploaded_file) -> str:
    sha = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in uploaded_file.chunks():
        sha.update(chunk)
    uploaded_file.seek(0)
    return sha.hexdigest()


# 扩展名 → 允许的 MIME（防"改名通过扩展名校验但 content_type 是脚本/可执行"）
EXT_MIME_WHITELIST = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg", "image/jpg"},
    "jpeg": {"image/jpeg", "image/jpg"},
    "gif": {"image/gif"},
    "webp": {"image/webp"},
    "doc": {"application/msword"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xls": {"application/vnd.ms-excel"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "zip": {"application/zip", "application/x-zip-compressed"},
    "txt": {"text/plain"},
}


def validate_upload(uploaded_file, *, allowed_formats=None, max_size_mb=None) -> dict:
    """
    校验 MIME/扩展名（防双扩展名 + content_type 一致性）/大小。返回 meta dict 或抛 ValueError。
    """
    name = uploaded_file.name or ""
    base, ext = os.path.splitext(name)
    ext = ext.lstrip(".").lower()
    if not ext:
        raise ValueError("NO_EXTENSION")
    if allowed_formats and ext not in allowed_formats:
        raise ValueError(f"FORMAT_NOT_ALLOWED:{ext}")
    # 防双扩展名（伪装脚本藏在白名单扩展名后）
    if ext in ("html", "htm", "svg", "js", "exe", "sh") and base.lower().endswith(
        (".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx", ".zip")
    ):
        raise ValueError("DOUBLE_EXTENSION")
    # content_type 一致性：若扩展名在映射表内，content_type 必须匹配（拒绝改名绕过）
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower().split(";")[0].strip()
    if ext in EXT_MIME_WHITELIST:
        if content_type and content_type not in EXT_MIME_WHITELIST[ext]:
            raise ValueError(f"MIME_MISMATCH:{ext}:{content_type}")
    size = uploaded_file.size
    if max_size_mb and size > max_size_mb * 1024 * 1024:
        raise ValueError(f"FILE_TOO_LARGE:{max_size_mb}")
    return {
        "original_name": name,
        "ext": ext,
        "size": size,
        "sha256": compute_sha256(uploaded_file),
        "mime": content_type,
    }


def store_material_file(
    uploaded_file,
    *,
    tenant_id: int,
    case_id,
    material_id,
    allowed_formats=None,
    max_size_mb=None,
) -> dict:
    """
    私有存储：onboarding/{tenant}/{case}/{material}/{uuid}.{ext}
    返回 file_version_id + meta（不暴露真实存储路径）。
    格式/大小白名单由 requirement 提供，缺省仅做双扩展名防护。
    注意：storage_path 不写入持久化 meta（避免泄漏内部路径），下载时按 file_version_id 重建。
    """
    meta = validate_upload(
        uploaded_file, allowed_formats=allowed_formats, max_size_mb=max_size_mb
    )
    file_version_id = uuid.uuid4()
    path = f"hr05/{tenant_id}/{case_id}/{material_id}/{file_version_id.hex}.{meta['ext']}"
    default_storage.save(path, uploaded_file)
    # meta 仅含展示/校验元数据，不含 storage_path
    meta.pop("storage_path", None)
    meta["file_version_id"] = str(file_version_id)
    return meta


def material_storage_path(*, tenant_id: int, case_id, material_id, file_version_id, ext) -> str:
    """按持久化元数据重建内部存储路径（下载用，不暴露给业务层）。"""
    return f"hr05/{tenant_id}/{case_id}/{material_id}/{file_version_id}.{ext}"


def issue_download_ticket(*, tenant_id: int, material_id) -> str:
    """短时效一次性下载 ticket（不暴露存储路径）。"""
    ticket = secrets.token_urlsafe(24)
    cache.set(
        f"hr05:fileticket:{ticket}",
        {"tenant_id": tenant_id, "material_id": str(material_id)},
        timeout=TICKET_TTL_SECONDS,
    )
    return ticket


def resolve_download_ticket(ticket: str) -> Optional[dict]:
    return cache.get(f"hr05:fileticket:{ticket}")


def consume_download_ticket(ticket: str) -> None:
    """一次性消费：删除 ticket，防止复用。"""
    cache.delete(f"hr05:fileticket:{ticket}")
