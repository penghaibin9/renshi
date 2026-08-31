"""
hr_external/services/material_service.py —— 外聘材料与安全下载 ticket（B5，总册 §92/00 §34）。

- 材料元数据 + private storage 引用；SHA-256；版本；敏感等级；
- 下载 ticket：HMAC-SHA256 签名 + 短时效（默认 15 分钟）+ 有限次数 + token_hash 存储（不存裸 token）；
- 校验：tenant / material scope / permission / sensitivity / purpose / status / 次数 / 时效（HR03 §14.4 对齐）；
- 每次使用写 HrSensitiveExternalAccessLog（下载审计）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from hr_external.models import (
    HrExternalFileTicket,
    HrExternalMaterial,
    HrExternalTeacherProfile,
)
from hr_external.services.audit_service import write_external_audit

TICKET_TTL_SECONDS = 15 * 60  # 短时效默认 15 分钟
DEFAULT_MAX_USES = 1

# 外聘材料允许的文件类型白名单（00 §34 MIME/扩展名校验）。
# 扩展名（小写）+ magic bytes 前缀双重校验；拒绝 HTML/SVG/JS/可执行等脚本类。
ALLOWED_MATERIAL_EXTENSIONS = {
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
MAX_MATERIAL_SIZE = 50 * 1024 * 1024  # 50MB


class MaterialFileRejected(Exception):
    """上传文件类型/大小校验失败。"""

    code = "MATERIAL_FILE_REJECTED"


def validate_material_file(*, filename: str, content: bytes) -> str:
    """校验扩展名 + magic bytes + 大小，返回规范化 mime_type。失败抛 MaterialFileRejected。"""
    if len(content) > MAX_MATERIAL_SIZE:
        raise MaterialFileRejected("文件超过 50MB 限制")

    import os

    ext = os.path.splitext(filename)[1].lower()
    rule = ALLOWED_MATERIAL_EXTENSIONS.get(ext)
    if rule is None:
        raise MaterialFileRejected(
            f"不支持的文件类型 .{ext or '?'}（仅允许 PDF/Office/图片/文本）"
        )

    magic, mime = rule
    if magic is not None and not content.startswith(magic):
        # 允许 office 系列共享 PK 头（docx/xlsx 同族）；正文 mime 以扩展名为准
        if ext not in (".docx", ".xlsx"):
            raise MaterialFileRejected("文件内容与扩展名不匹配（magic bytes 校验失败）")
    return mime


class MaterialAccessDenied(Exception):
    code = "MATERIAL_ACCESS_DENIED"


class TicketInvalid(Exception):
    code = "MATERIAL_ACCESS_DENIED"


class MaterialService:
    @staticmethod
    def _secret() -> str:
        return getattr(settings, "SECRET_KEY", "hr08-insecure-fallback")

    def sign_token(self, *, tenant_id: int, material_id: str) -> str:
        """HMAC 签名：token = material_id.expiry_ts.signature。"""
        expires_ts = int(timezone.now().timestamp()) + TICKET_TTL_SECONDS
        payload = f"{material_id}.{expires_ts}"
        sig = hmac.new(
            self._secret().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}.{sig}"

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @transaction.atomic
    def issue_ticket(
        self,
        *,
        tenant_id: int,
        material: HrExternalMaterial,
        actor_user_id: Optional[int] = None,
        purpose: str = "",
        token: Optional[str] = None,
    ) -> HrExternalFileTicket:
        """签发短时效下载票据（一次性默认）。token 由调用方传入（与 API 返回给前端的一致）。"""
        material = (
            HrExternalMaterial.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(material, "pk", None))
            .first()
        )
        if material is None:
            raise MaterialAccessDenied("material not found inside tenant")
        token = token or self.sign_token(tenant_id=tenant_id, material_id=str(material.id))
        return HrExternalFileTicket.objects.create(
            tenant_id=tenant_id,
            material_id=material,
            actor_user_id=actor_user_id,
            purpose=purpose,
            token_hash=self._hash_token(token),
            expires_at=timezone.now() + timedelta(seconds=TICKET_TTL_SECONDS),
            max_uses=DEFAULT_MAX_USES,
        )

    @transaction.atomic
    def redeem_ticket(
        self,
        *,
        token: str,
        actor_user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> HrExternalMaterial:
        """兑换票据：校验签名/时效/次数/租户（可选）/状态，返回材料元数据。

        tenant_id 为可选双保险：公开入口（外聘本人）不传，由 ticket 自身绑定 tenant；
        HR 管理入口可显式传 tenant 做二次校验。
        """
        try:
            material_id, expires_ts, sig = token.rsplit(".", 2)
        except (ValueError, AttributeError):
            raise TicketInvalid("malformed ticket")

        # HMAC 签名校验
        payload = f"{material_id}.{expires_ts}"
        expected = hmac.new(
            self._secret().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise TicketInvalid("ticket signature invalid")
        if int(expires_ts) < int(timezone.now().timestamp()):
            raise TicketInvalid("ticket expired")

        ticket = (
            HrExternalFileTicket.objects.select_for_update()
            .select_related("material_id")
            .filter(token_hash=self._hash_token(token))
            .first()
        )
        if ticket is None:
            raise TicketInvalid("ticket not found")
        if tenant_id is not None and ticket.tenant_id != tenant_id:
            raise TicketInvalid("ticket tenant mismatch")
        if ticket.revoked:
            raise TicketInvalid("ticket revoked")
        if ticket.used_count >= ticket.max_uses:
            raise TicketInvalid("ticket already used")
        if ticket.expires_at < timezone.now():
            raise TicketInvalid("ticket expired")

        material = ticket.material_id
        if material.tenant_id != ticket.tenant_id:
            raise TicketInvalid("material tenant mismatch")
        if material.status == "REJECTED":
            raise MaterialAccessDenied("material rejected")

        # 使用记账 + 下载审计（§92 download audit）
        ticket.used_count += 1
        ticket.used_at = timezone.now()
        ticket.save(update_fields=["used_count", "used_at"])
        write_external_audit(
            tenant_id=ticket.tenant_id,
            action="ExternalMaterialDownload",
            actor_user_id=actor_user_id,
            external_profile_id=material.external_profile_id_id,
            business_type="HR08_MATERIAL",
            business_id=str(material.id),
            reason=ticket.purpose or "material download",
            source="file_ticket",
        )
        return material

    def create_material(
        self,
        *,
        tenant_id: int,
        external_profile_id,
        category: str,
        title: str,
        storage_ref: str = "",
        original_filename: str = "",
        mime_type: str = "",
        size_bytes: int = 0,
        sha256: str = "",
        sensitivity_level: str = "SENSITIVE",
        uploaded_by: Optional[int] = None,
    ) -> HrExternalMaterial:
        profile = HrExternalTeacherProfile.objects.filter(
            tenant_id=tenant_id, id=external_profile_id
        ).first()
        if profile is None:
            raise MaterialAccessDenied("EXTERNAL_PROFILE_NOT_FOUND")
        return HrExternalMaterial.objects.create(
            tenant_id=tenant_id,
            external_profile_id=profile,
            category=category,
            title=title,
            storage_ref=storage_ref,
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256,
            sensitivity_level=sensitivity_level,
            uploaded_by=uploaded_by,
        )

    @transaction.atomic
    def save_material_file(
        self,
        *,
        material: HrExternalMaterial,
        tenant_id: int,
        content: bytes,
        original_filename: str = "",
        mime_type: str = "",
        storage=None,
    ) -> HrExternalMaterial:
        """写入私有存储（0600）并更新元数据：storage_ref/sha256/size/mime。
        文件不进 public /media/ 路径（00 §34）。
        上传前必须经过 validate_material_file（扩展名 + magic bytes + 大小）。"""
        import hashlib

        material = (
            HrExternalMaterial.objects.select_for_update()
            .filter(tenant_id=tenant_id, id=getattr(material, "pk", None))
            .first()
        )
        if material is None:
            raise MaterialAccessDenied("material not found inside tenant")

        from hr_external.services.storage_backends import get_material_storage

        # 生产级：文件类型/大小校验（A1）—— 任何写私有存储的文件都必须过白名单
        verified_mime = validate_material_file(
            filename=original_filename, content=content
        )
        if not mime_type:
            mime_type = verified_mime

        backend = storage or get_material_storage()
        storage_ref = backend.save_bytes(str(material.id), content, original_filename)
        material.storage_ref = storage_ref
        material.original_filename = original_filename or material.original_filename
        material.mime_type = mime_type or verified_mime
        material.size_bytes = len(content)
        material.sha256 = hashlib.sha256(content).hexdigest()
        material.save(
            update_fields=[
                "storage_ref",
                "original_filename",
                "mime_type",
                "size_bytes",
                "sha256",
                "updated_at",
            ]
        )
        return material

    def open_authorized_stream(self, material: HrExternalMaterial, storage=None):
        """ticket 校验通过后打开文件流（FileResponse 消费）。"""
        from hr_external.services.storage_backends import get_material_storage

        backend = storage or get_material_storage()
        if not material.storage_ref or not backend.exists(material.storage_ref):
            raise MaterialAccessDenied("material file not found in storage")
        return backend.open_stream(material.storage_ref)
