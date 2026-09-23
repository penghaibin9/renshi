"""Private, tenant-partitioned document storage for HR12 formal workflows."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import get_valid_filename

from hr_assessment.models import HrAssessmentDecisionSession, HrAssessmentDocument


MAX_ASSESSMENT_DOCUMENT_BYTES = 20 * 1024 * 1024
ALLOWED_MINUTES_TYPES = {
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
}


class AssessmentDocumentError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _sha256(upload) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


@transaction.atomic
def store_decision_minutes(
    upload,
    *,
    tenant_id: int,
    session_id,
    uploaded_by: int | None,
) -> HrAssessmentDocument:
    session = HrAssessmentDecisionSession.objects.select_for_update().filter(
        tenant_id=tenant_id,
        id=session_id,
    ).first()
    if session is None:
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_SESSION_NOT_FOUND",
            "未找到当前学校的审定会议",
            status=404,
        )
    if session.status != "DRAFT":
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_INVALID_STATE",
            "只有待完成的审定会议可以上传会议纪要",
            status=409,
        )
    if upload is None:
        raise AssessmentDocumentError("ASSESSMENT_DECISION_MINUTES_REQUIRED", "请选择会议纪要文件")
    if getattr(settings, "MALWARE_SCAN_REQUIRED", False) and not getattr(
        upload, "_malware_scan_complete", False
    ):
        raise AssessmentDocumentError(
            "MALWARE_SCAN_REQUIRED", "会议纪要尚未通过安全检查", status=503
        )
    size = int(getattr(upload, "size", 0) or 0)
    if size <= 0:
        raise AssessmentDocumentError("ASSESSMENT_DECISION_MINUTES_EMPTY", "会议纪要文件不能为空")
    if size > MAX_ASSESSMENT_DOCUMENT_BYTES:
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_MINUTES_TOO_LARGE",
            "会议纪要文件不能超过 20 MiB",
            status=413,
        )
    filename = get_valid_filename(Path(str(getattr(upload, "name", ""))).name)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_MINUTES_TYPES:
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_MINUTES_TYPE_INVALID",
            "会议纪要仅支持 PDF 或 Word 文档",
        )
    content_type = str(getattr(upload, "content_type", "") or "").split(";", 1)[0].lower()
    if content_type not in ALLOWED_MINUTES_TYPES[suffix]:
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_MINUTES_TYPE_INVALID",
            "会议纪要扩展名与内容类型不一致",
        )
    digest = _sha256(upload)
    existing = HrAssessmentDocument.objects.filter(
        tenant_id=tenant_id,
        document_type="DECISION_MINUTES",
        related_object_type="DECISION_SESSION",
        related_object_id=session.id,
    ).first()
    if existing is not None:
        if existing.sha256 == digest and existing.size_bytes == size:
            return existing
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_MINUTES_ALREADY_UPLOADED",
            "该审定会议已上传纪要；如需更换，请走受控更正流程",
            status=409,
        )
    storage_key = (
        f"protected/hr12/{int(tenant_id)}/decision-minutes/{session.id}/"
        f"{uuid.uuid4().hex}{suffix}"
    )
    saved_key = default_storage.save(storage_key, upload)
    try:
        return HrAssessmentDocument.objects.create(
            tenant_id=tenant_id,
            document_type="DECISION_MINUTES",
            related_object_type="DECISION_SESSION",
            related_object_id=session.id,
            storage_key=saved_key,
            original_filename=(filename or f"meeting-minutes{suffix}")[:255],
            content_type=content_type[:127],
            size_bytes=size,
            sha256=digest,
            uploaded_by=uploaded_by,
            sealed_at=timezone.now(),
            status="SEALED",
        )
    except (IntegrityError, ValueError):
        if default_storage.exists(saved_key):
            default_storage.delete(saved_key)
        raise


def resolve_decision_minutes(*, tenant_id: int, session_id, document_id) -> HrAssessmentDocument:
    document = HrAssessmentDocument.objects.filter(
        tenant_id=tenant_id,
        id=document_id,
        document_type="DECISION_MINUTES",
        related_object_type="DECISION_SESSION",
        related_object_id=session_id,
        status="SEALED",
    ).first()
    if document is None or not default_storage.exists(document.storage_key):
        raise AssessmentDocumentError(
            "ASSESSMENT_DECISION_MINUTES_NOT_FOUND",
            "会议纪要不存在、未封存或不属于本次审定会议",
            status=404,
        )
    return document


def open_verified_document(document):
    """R11 routes/files.py::verify_file, adapted to HR12 protected storage.

    Authenticate/authorize the business object before calling. Return the very
    bytes checked (no second open / public URL), in a bounded private spool.
    This checks existing sealed bytes, not a replacement malware scan.
    """
    import hmac
    import os
    import re
    import stat
    import tempfile
    from pathlib import PurePosixPath
    from django.core.files.storage import FileSystemStorage

    key = str(document.storage_key or '')
    parts = PurePosixPath(key).parts
    expected_prefix = ('protected', 'hr12', str(document.tenant_id))
    if (document.status != 'SEALED' or not document.sealed_at
        or not re.fullmatch(r'[0-9a-f]{64}', str(document.sha256 or ''))
        or not 0 < int(document.size_bytes or 0) <= MAX_ASSESSMENT_DOCUMENT_BYTES
        or '\\' in key or key.startswith('/') or any(p in {'.', '..'} for p in key.split('/'))
        or parts[:3] != expected_prefix):
        raise AssessmentDocumentError('ASSESSMENT_DOCUMENT_INTEGRITY_INVALID', '文件封存元数据或受控路径无效。', status=409)
    spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
    stream = None
    try:
        if isinstance(default_storage, FileSystemStorage) and hasattr(os, 'O_NOFOLLOW'):
            # Walk from the configured storage root with dir-fds, rejecting symlinks
            # at each component. No untrusted pathname can switch the opened root.
            directory = os.open(default_storage.location, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for component in parts[:-1]:
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory)
                    directory = child
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory)
                stream = os.fdopen(fd, 'rb')
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != document.size_bytes:
                    raise ValueError('file size/type mismatch')
            finally:
                os.close(directory)
        else:
            stream = default_storage.open(key, 'rb')
        total, checksum = 0, hashlib.sha256()
        with stream:
            while True:
                chunk = stream.read(min(65536, int(document.size_bytes) - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > document.size_bytes:
                    raise ValueError('stored file is larger than sealed size')
                checksum.update(chunk)
                spool.write(chunk)
        stream = None
        if total != document.size_bytes or not hmac.compare_digest(checksum.hexdigest(), document.sha256):
            raise ValueError('stored file checksum mismatch')
        spool.seek(0)
        return spool
    except Exception as exc:
        if stream is not None:
            stream.close()
        spool.close()
        raise AssessmentDocumentError(
            'ASSESSMENT_DOCUMENT_BYTES_INVALID',
            '文件内容与封存指纹不一致或无法读取，禁止下载或用于新归档。', status=409,
        ) from exc
