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

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

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
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        uploaded_file, "_malware_scan_complete", False
    ):
        raise ValueError("MALWARE_SCAN_REQUIRED")
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
    try:
        tenant_id = int(tenant_id)
        case_id = uuid.UUID(str(case_id))
        material_id = uuid.UUID(str(material_id))
        file_version_id = uuid.UUID(str(file_version_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("MATERIAL_STORAGE_ID_INVALID") from exc
    ext = str(ext or "").strip().lower().lstrip(".")
    if ext not in EXT_MIME_WHITELIST:
        raise ValueError("MATERIAL_STORAGE_EXTENSION_INVALID")
    return (
        f"hr05/{tenant_id}/{case_id}/{material_id}/"
        f"{file_version_id.hex}.{ext}"
    )


def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(str(ticket or "").encode("utf-8")).hexdigest()


def issue_download_ticket(
    *,
    tenant_id: int,
    material,
    actor_user_id: int,
    purpose: str,
    request_id: str = "",
) -> str:
    """签发持久化、账号绑定、文件版本绑定的一次性下载票据。"""

    from hr_onboarding.models import HrOnboardingMaterialDownloadTicket

    purpose = str(purpose or "").strip()
    if not purpose:
        raise ValueError("MATERIAL_DOWNLOAD_PURPOSE_REQUIRED")
    if len(purpose) > 500:
        raise ValueError("MATERIAL_DOWNLOAD_PURPOSE_INVALID")
    if material is None or int(material.tenant_id) != int(tenant_id):
        raise ValueError("MATERIAL_DOWNLOAD_SCOPE_INVALID")
    if not material.file_version_id:
        raise ValueError("MATERIAL_DOWNLOAD_FILE_MISSING")
    ticket = secrets.token_urlsafe(24)
    HrOnboardingMaterialDownloadTicket.objects.create(
        tenant_id=int(tenant_id),
        material=material,
        file_version_id=material.file_version_id,
        token_hash=_ticket_hash(ticket),
        actor_user_id=int(actor_user_id),
        purpose=purpose,
        request_id=str(request_id or "")[:64],
        expires_at=timezone.now() + timedelta(seconds=TICKET_TTL_SECONDS),
    )
    return ticket


@transaction.atomic
def consume_download_ticket(*, ticket: str, tenant_id: int, actor_user_id: int):
    """原子消费一次性票据；过期、跨账号、跨学校或旧文件版本均拒绝。"""

    from hr_onboarding.models import HrOnboardingMaterialDownloadTicket

    record = (
        HrOnboardingMaterialDownloadTicket.objects.select_for_update()
        .select_related("material")
        .filter(token_hash=_ticket_hash(ticket))
        .first()
    )
    now = timezone.now()
    if (
        record is None
        or record.consumed_at is not None
        or record.expires_at <= now
        or int(record.tenant_id) != int(tenant_id)
        or int(record.actor_user_id) != int(actor_user_id)
        or record.material.tenant_id != record.tenant_id
        or record.material.file_version_id != record.file_version_id
    ):
        raise ValueError("MATERIAL_DOWNLOAD_TICKET_INVALID")
    record.consumed_at = now
    record.save(update_fields=["consumed_at"])
    return record
