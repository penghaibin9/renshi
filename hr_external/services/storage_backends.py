"""
hr_external/services/storage_backends.py —— 外聘材料私有存储（任务 2，总册 §92/00 §34）。

- 抽象 backend 接口：未来 horilla_documents/对象存储就绪时替换实现，消费方（MaterialService/API）不动。
- PrivateFileSystemStorage：独立私有目录（默认 MEDIA_ROOT/external-materials/），
  文件权限 0600、目录 0700，不在 public 路径；文件名 uuid，杜绝可猜 URL。
- 下载一律走 HMAC ticket 校验后由 API 流式返回（不经 /media/ 裸 URL）。
"""

from __future__ import annotations

import io
import uuid
from typing import BinaryIO, Optional

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class ExternalMaterialStorage:
    """存储后端抽象（消费方只依赖本接口）。"""

    def save_bytes(self, material_id: str, content: bytes, original_filename: str) -> str:
        """写入私有存储，返回 storage_ref。"""
        raise NotImplementedError

    def open_stream(self, storage_ref: str) -> BinaryIO:
        """打开已授权文件的二进制流（调用方必须先过 ticket 校验）。"""
        raise NotImplementedError

    def exists(self, storage_ref: str) -> bool:
        raise NotImplementedError

    def delete(self, storage_ref: str) -> None:
        raise NotImplementedError


def _private_root() -> str:
    """私有存储根目录：HR08_PRIVATE_STORAGE_ROOT > MEDIA_ROOT/external-materials > tempfile。"""
    custom = getattr(settings, "HR08_PRIVATE_STORAGE_ROOT", "")
    if custom:
        return str(custom)
    media = getattr(settings, "MEDIA_ROOT", "") or ""
    if media:
        import os

        return os.path.join(str(media), "external-materials")
    import tempfile

    return tempfile.mkdtemp(prefix="hr08-private-")


class PrivateFileSystemStorage(ExternalMaterialStorage):
    """FileSystemStorage 最小实现（私有目录 + 0600/0700 + uuid 文件名）。"""

    def __init__(self, location: Optional[str] = None):
        self._location = location or _private_root()
        self._fs = FileSystemStorage(
            location=self._location,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )

    @property
    def location(self) -> str:
        return self._location

    @staticmethod
    def _safe_storage_ref(storage_ref: str) -> str:
        """路径穿越防护（A2）：拒绝绝对路径 / .. / 反斜杠 / 空名。"""
        if not storage_ref or not isinstance(storage_ref, str):
            raise ValueError("invalid storage_ref")
        if storage_ref.startswith(("/", "\\")) or "\\" in storage_ref:
            raise ValueError("invalid storage_ref")
        normalized = storage_ref.replace("\\", "/")
        if "/" in normalized:
            raise ValueError("invalid storage_ref: nested path not allowed")
        if normalized in (".", ".."):
            raise ValueError("invalid storage_ref")
        return normalized

    def save_bytes(self, material_id: str, content: bytes, original_filename: str) -> str:
        name = f"{uuid.uuid4().hex}_{material_id[:8]}"
        self._fs.save(name, io.BytesIO(content))
        return name

    def open_stream(self, storage_ref: str) -> BinaryIO:
        safe = self._safe_storage_ref(storage_ref)
        if not self._fs.exists(safe):
            raise FileNotFoundError("storage ref not found")
        return self._fs.open(safe, "rb")

    def exists(self, storage_ref: str) -> bool:
        try:
            safe = self._safe_storage_ref(storage_ref)
        except ValueError:
            return False
        return self._fs.exists(safe)

    def delete(self, storage_ref: str) -> None:
        try:
            safe = self._safe_storage_ref(storage_ref)
        except ValueError:
            return
        if self._fs.exists(safe):
            self._fs.delete(safe)


_default_storage: Optional[ExternalMaterialStorage] = None


def get_material_storage() -> ExternalMaterialStorage:
    """获取当前存储后端（默认私有文件系统；未来可换对象存储/文档服务）。"""
    global _default_storage
    if _default_storage is None:
        _default_storage = PrivateFileSystemStorage()
    return _default_storage
