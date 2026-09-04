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
