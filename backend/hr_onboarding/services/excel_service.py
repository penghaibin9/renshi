"""
hr_onboarding/services/excel_service.py

Excel 导入（总册 §42 · 最小生产级实现）

流程：模板下载 → 上传 → staging 解析 → 业务校验 → error workbook → 确认 → async 执行 → result
禁止 Excel 直接绕过 Activation Service。

V1 支持：报到人员名单批量创建 case（source=HR04_HIRE 或 LEGACY_MIGRATION）。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
import zipfile
from pathlib import Path
from datetime import date, datetime
from typing import Optional

from django.db import transaction
from django.db.models import Count
from django.utils.translation import gettext as _
from django.utils import timezone

from hr_onboarding.constants import CaseSourceType, EmploymentType, StaffCategoryCode

logger = logging.getLogger(__name__)

BATCH_CASE_TEMPLATE_COLS = [
    "legal_name",       # 姓名
    "source_type",      # 来源类型（HR04_HIRE / LEGACY_MIGRATION）
    "source_id",        # 来源标识
    "expected_report_date",  # 预计报到日
    "employment_type",  # 用工类型
    "staff_category",   # 人员类别
    "note",             # 备注
]

REQUIRED_COLS = {"legal_name", "source_type", "expected_report_date"}

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
MAX_CELL_CHARS = 500
MAX_XLSX_ENTRIES = 2000
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
COMMIT_STALE_SECONDS = 15 * 60


class ExcelImportStateError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class ExcelValidationError(Exception):
    def __init__(self, row: int, field: str, message: str):
        self.row = row
        self.field = field
        self.message = message
        super().__init__(f"row={row} field={field}: {message}")


class ExcelImportJob:
    """Excel 导入作业（staging → validate → confirm）。"""

    class Status:
        UPLOADED = "UPLOADED"
        VALIDATING = "VALIDATING"
        VALIDATION_FAILED = "VALIDATION_FAILED"
        READY_TO_COMMIT = "READY_TO_COMMIT"
        COMMITTING = "COMMITTING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    def __init__(self, *, tenant_id: int, uploaded_by: int):
        self.tenant_id = tenant_id
        self.uploaded_by = uploaded_by
        self.job_id = str(uuid.uuid4())
        self.status = self.Status.UPLOADED
        self.rows = []
        self.errors = []
        self.result = {}

    def parse(
        self,
        uploaded_file,
        *,
        sheet_name: str = "Sheet1",
        expected_cols: Optional[list] = None,
    ) -> int:
        """解析上传文件为 staging rows（读第一 sheet，第一行作表头）。返回行数。"""
        try:
            import openpyxl
        except ImportError:
            raise ImportError(_("缺少 openpyxl 库。pip install openpyxl"))

        size = getattr(uploaded_file, "size", None)
        if size is not None and int(size) > MAX_IMPORT_BYTES:
            raise ExcelImportStateError("EXCEL_FILE_TOO_LARGE", "Excel 文件不得超过 10 MiB")

        try:
            wb = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=False)
        except Exception as exc:  # noqa: BLE001 - normalize parser failures at API boundary
            raise ExcelImportStateError("EXCEL_FILE_INVALID", "Excel 文件无法解析或格式损坏") from exc
        if sheet_name not in wb.sheetnames:
            sheet_name = wb.sheetnames[0]

        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = [str(h or "").strip() if h else "" for h in next(rows_iter)]
        except StopIteration as exc:
            wb.close()
            raise ExcelImportStateError("EXCEL_EMPTY_WORKBOOK", "Excel 工作簿没有表头") from exc

        non_empty_headers = [value for value in header if value]
        duplicates = sorted({value for value in non_empty_headers if non_empty_headers.count(value) > 1})
        if duplicates:
            wb.close()
            raise ExcelImportStateError(
                "EXCEL_DUPLICATE_HEADER",
                f"Excel 表头存在重复字段: {', '.join(duplicates[:10])}",
            )
        missing = sorted(REQUIRED_COLS.difference(non_empty_headers))
        if missing:
            wb.close()
            raise ExcelImportStateError(
                "EXCEL_REQUIRED_HEADER_MISSING",
                f"Excel 缺少必需表头: {', '.join(missing)}",
            )

        col_index = {h: i for i, h in enumerate(header) if h}
        cols = expected_cols or BATCH_CASE_TEMPLATE_COLS
        self.status = self.Status.VALIDATING
        row_count = 0
        for row_data in rows_iter:
            if row_count >= MAX_IMPORT_ROWS:
                wb.close()
                raise ExcelImportStateError(
                    "EXCEL_ROW_LIMIT_EXCEEDED",
                    f"单次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件后重试",
                )
            row_no = row_count + 2  # 1-indexed, skip header
            record = {}
            for col in cols:
                idx = col_index.get(col)
                raw = str(row_data[idx]).strip() if idx is not None and row_data[idx] is not None else ""
                if len(raw) > MAX_CELL_CHARS:
                    wb.close()
                    raise ExcelImportStateError(
                        "EXCEL_CELL_TOO_LONG",
                        f"第 {row_no} 行字段 {col} 超过 {MAX_CELL_CHARS} 字符",
                    )
                record[col] = raw
            record["_row"] = row_no
            self.rows.append(record)
            row_count += 1
        wb.close()
        if row_count == 0:
            raise ExcelImportStateError("EXCEL_EMPTY_WORKBOOK", "Excel 工作簿没有可导入的数据行")
        return row_count

    def validate(self) -> bool:
        """校验 staging 数据。返回 True 表示全部合法。"""
        self.errors = []
        for i, record in enumerate(self.rows):
            try:
                self._validate_row(i, record)
            except ExcelValidationError as exc:
                self.errors.append({"row": exc.row, "field": exc.field, "message": exc.message})

        if self.errors:
            self.status = self.Status.VALIDATION_FAILED
            return False
        self.status = self.Status.READY_TO_COMMIT
        return True

    def _validate_row(self, i, record):
        row = record["_row"]
        for col in REQUIRED_COLS:
            if not record.get(col):
                raise ExcelValidationError(row, col, "必填")

        st = record.get("source_type", "")
        if st and st not in CaseSourceType.values:
            raise ExcelValidationError(row, "source_type", f"无效来源: {st}")
        if st and st != CaseSourceType.LEGACY_MIGRATION and not record.get("source_id"):
            raise ExcelValidationError(row, "source_id", f"{st} 必须填写真实来源标识")

        et = record.get("employment_type", "")
        if et and et not in EmploymentType.values:
            raise ExcelValidationError(row, "employment_type", f"无效用工类型: {et}")

        sc = record.get("staff_category", "")
        if sc and sc not in StaffCategoryCode.values:
            raise ExcelValidationError(row, "staff_category", f"无效人员类别: {sc}")

        dr = record.get("expected_report_date", "")
        if dr:
            try:
                date.fromisoformat(dr)
            except ValueError:
                raise ExcelValidationError(row, "expected_report_date", f"日期格式非法: {dr}")

    def error_workbook(self) -> bytes:
        """生成错误工作簿（xlsx）。"""
        try:
            import openpyxl
        except ImportError:
            return b""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "errors"
        ws.append(["row", "field", "message"])
        for e in self.errors:
            ws.append([e["row"], e["field"], e["message"]])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.getvalue()

    def commit_async(self) -> dict:
        """
        异步确认执行（逐行幂等：source_type+source_id unique 兜底）。
        禁止绕过 Activation Service（不直接建 Employment/Assignment）。
        """
        from hr_onboarding.services.case_service import CaseService

        self.status = self.Status.COMMITTING
        created = 0
        skipped = 0
        errors = []
        for record in self.rows:
            try:
                request = {
                    "source_type": record.get("source_type", "LEGACY_MIGRATION"),
                    "source_id": record.get("source_id") or f"excel:{self.job_id}:{record['_row']}",
                    "legal_name": record.get("legal_name", ""),
                    "employment_type": record.get("employment_type", "FULL_TIME"),
                    "staff_category": record.get("staff_category", "TEACHER"),
                    "expected_report_date": record.get("expected_report_date"),
                }
                service = CaseService(tenant_id=self.tenant_id)
                key = f"excel-import-{self.job_id}-{record['_row']}"
                result = service.create_case_from_handoff(request, idempotency_key=key)
                if result.get("created"):
                    created += 1
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"row": record["_row"], "error": str(exc)})
        if errors:
            self.status = self.Status.FAILED
        else:
            self.status = self.Status.COMPLETED
        self.result = {"created": created, "skipped": skipped, "errors": errors}
        return self.result

    def template_bytes(self) -> bytes:
        """生成空白导入模板（xlsx）。"""
        try:
            import openpyxl
        except ImportError:
            return b""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "import"
        ws.append(BATCH_CASE_TEMPLATE_COLS)
        # 示例行
        ws.append(["张三", "HR04_HIRE", "PH-2026-001", "2026-09-01", "FULL_TIME", "TEACHER", "示例"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Durable production ledger (multi-worker/restart safe)
# ---------------------------------------------------------------------------

def _validate_xlsx_archive(content: bytes) -> None:
    """Reject malformed/oversized XLSX ZIPs before openpyxl expands XML parts."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_XLSX_ENTRIES:
                raise ExcelImportStateError(
                    "EXCEL_ARCHIVE_TOO_COMPLEX",
                    f"Excel 压缩包条目过多（>{MAX_XLSX_ENTRIES}）",
                )
            total_uncompressed = 0
            for info in infos:
                # XLSX is an OPC ZIP package. Paths must remain relative and must
                # not escape the archive root even though we never extract them.
                name = str(info.filename or "")
                # OPC/XLSX canonical names use forward slashes. Reject Windows
                # separators too so ``..\evil`` cannot evade POSIX Path.parts.
                parts = Path(name).parts
                if (
                    not name
                    or "\\" in name
                    or name.startswith(("/", "\\"))
                    or ":" in parts[0]
                    or ".." in parts
                ):
                    raise ExcelImportStateError("EXCEL_ARCHIVE_INVALID", "Excel 压缩包路径非法")
                total_uncompressed += max(int(info.file_size or 0), 0)
                if total_uncompressed > MAX_XLSX_UNCOMPRESSED_BYTES:
                    raise ExcelImportStateError(
                        "EXCEL_ARCHIVE_TOO_LARGE",
                        "Excel 解压后内容不得超过 50 MiB",
                    )
            if "[Content_Types].xml" not in archive.namelist():
                raise ExcelImportStateError("EXCEL_ARCHIVE_INVALID", "文件不是有效的 XLSX 工作簿")
    except ExcelImportStateError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ExcelImportStateError("EXCEL_FILE_INVALID", "Excel 文件无法解析或格式损坏") from exc


def _read_upload_bytes(uploaded_file) -> bytes:
    name = str(getattr(uploaded_file, "name", "") or "")
    if Path(name).suffix.lower() != ".xlsx":
        raise ExcelImportStateError("EXCEL_FILE_TYPE_INVALID", "仅支持 .xlsx 文件")
    size = getattr(uploaded_file, "size", None)
    if size is not None and int(size) > MAX_IMPORT_BYTES:
        raise ExcelImportStateError("EXCEL_FILE_TOO_LARGE", "Excel 文件不得超过 10 MiB")
    chunks = getattr(uploaded_file, "chunks", None)
    if callable(chunks):
        parts = []
        total = 0
        for chunk in chunks():
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                raise ExcelImportStateError("EXCEL_FILE_TOO_LARGE", "Excel 文件不得超过 10 MiB")
            parts.append(chunk)
        data = b"".join(parts)
    else:
        data = uploaded_file.read()
        if len(data) > MAX_IMPORT_BYTES:
            raise ExcelImportStateError("EXCEL_FILE_TOO_LARGE", "Excel 文件不得超过 10 MiB")
    _validate_xlsx_archive(data)
    return data


def _safe_file_name(uploaded_file) -> str:
    value = Path(str(getattr(uploaded_file, "name", "import.xlsx") or "import.xlsx")).name
    return value[:255] or "import.xlsx"


def _errors_by_row(parser: ExcelImportJob) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for item in parser.errors:
        grouped.setdefault(int(item["row"]), []).append(
            {"field": str(item.get("field") or "")[:64], "message": str(item.get("message") or "")[:500]}
        )
    return grouped


def stage_persisted_import(*, tenant_id: int, uploaded_by: int | None, uploaded_file):
    """Parse/validate one workbook and persist its staging ledger atomically."""

    from hr_onboarding.models import (
        HrOnboardingAuditEvent,
        HrOnboardingImportJob,
        HrOnboardingImportRow,
    )

    content = _read_upload_bytes(uploaded_file)
    source_sha256 = hashlib.sha256(content).hexdigest()
    parser = ExcelImportJob(tenant_id=int(tenant_id), uploaded_by=int(uploaded_by or 0))
    parser.parse(io.BytesIO(content))
    parser.validate()
    grouped = _errors_by_row(parser)
    now = timezone.now()

    with transaction.atomic():
        job = HrOnboardingImportJob.objects.create(
            tenant_id=int(tenant_id),
            uploaded_by=uploaded_by,
            file_name=_safe_file_name(uploaded_file),
            source_sha256=source_sha256,
            status=(
                HrOnboardingImportJob.Status.VALIDATION_FAILED
                if parser.errors
                else HrOnboardingImportJob.Status.READY_TO_COMMIT
            ),
            row_count=len(parser.rows),
            error_count=len(parser.errors),
            validated_at=now,
        )
        rows = []
        for record in parser.rows:
            row_no = int(record["_row"])
            errors = grouped.get(row_no, [])
            payload = {key: value for key, value in record.items() if key != "_row"}
            rows.append(
                HrOnboardingImportRow(
                    tenant_id=int(tenant_id),
                    job=job,
                    row_no=row_no,
                    payload_json=payload,
                    status=(
                        HrOnboardingImportRow.Status.INVALID
                        if errors
                        else HrOnboardingImportRow.Status.VALID
                    ),
                    error_json=errors,
                )
            )
        HrOnboardingImportRow.objects.bulk_create(rows, batch_size=500)
        HrOnboardingAuditEvent.objects.create(
            tenant_id=int(tenant_id),
            actor_user_id=uploaded_by,
            action="EXCEL_IMPORT_STAGED",
            business_type="EXCEL_IMPORT",
            business_id=str(job.id),
            reason=(
                f"source_sha256={source_sha256}; rows={job.row_count}; "
                f"validation_errors={job.error_count}"
            ),
        )
    return job


def get_persisted_import(*, tenant_id: int, job_id):
    from hr_onboarding.models import HrOnboardingImportJob

    return HrOnboardingImportJob.objects.filter(
        tenant_id=int(tenant_id), id=job_id
    ).first()


def serialize_persisted_import(job) -> dict:
    return {
        "job_id": str(job.id),
        "file_name": job.file_name,
        "source_sha256": job.source_sha256,
        "status": job.status,
        "rows": int(job.row_count),
        "errors": int(job.error_count),
        "created": int(job.created_count),
        "skipped": int(job.skipped_count),
        "failed": int(job.failed_count),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "validated_at": job.validated_at.isoformat() if job.validated_at else None,
        "confirmed_at": job.confirmed_at.isoformat() if job.confirmed_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def persisted_error_workbook(job) -> bytes:
    """Rebuild validation/commit errors from durable rows; no in-memory job needed."""
    try:
        import openpyxl
    except ImportError:
        return b""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "errors"
    ws.append(["row", "field", "message", "status"])
    for row in job.rows.exclude(error_json=[]).order_by("row_no").iterator(chunk_size=500):
        errors = row.error_json if isinstance(row.error_json, list) else []
        for item in errors:
            ws.append(
                [
                    row.row_no,
                    str(item.get("field") or ""),
                    str(item.get("message") or ""),
                    row.status,
                ]
            )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def confirm_persisted_import(*, tenant_id: int, job_id, actor_user_id: int | None):
    """Confirm a validated job without doing row work in the HTTP request.

    ``COMMITTING`` with ``commit_started_at=NULL`` means durable queued work.
    The dedicated HR05 import worker claims it by setting ``commit_started_at``.
    Repeated confirmation is idempotent.
    """
    from hr_onboarding.models import HrOnboardingAuditEvent, HrOnboardingImportJob

    with transaction.atomic():
        job = HrOnboardingImportJob.objects.select_for_update().filter(
            tenant_id=int(tenant_id), id=job_id
        ).first()
        if job is None:
            raise ExcelImportStateError("EXCEL_JOB_NOT_FOUND", "导入作业不存在")
        if job.status == HrOnboardingImportJob.Status.COMPLETED:
            return job
        if job.status == HrOnboardingImportJob.Status.VALIDATION_FAILED:
            raise ExcelImportStateError("EXCEL_VALIDATION_FAILED", "导入文件存在校验错误，请先下载错误表")
        if job.status == HrOnboardingImportJob.Status.FAILED:
            raise ExcelImportStateError("EXCEL_COMMIT_FAILED", "导入作业已失败，请查看错误表后重新上传")
        if job.status == HrOnboardingImportJob.Status.COMMITTING:
            return job
        if job.status != HrOnboardingImportJob.Status.READY_TO_COMMIT:
            raise ExcelImportStateError("EXCEL_JOB_STATE_INVALID", f"当前状态 {job.status} 不可确认导入")
        job.status = HrOnboardingImportJob.Status.COMMITTING
        job.confirmed_by = actor_user_id
        job.confirmed_at = timezone.now()
        job.commit_started_at = None
        job.save(
            update_fields=[
                "status", "confirmed_by", "confirmed_at", "commit_started_at", "updated_at"
            ]
        )
        HrOnboardingAuditEvent.objects.create(
            tenant_id=int(tenant_id),
            actor_user_id=actor_user_id,
            action="EXCEL_IMPORT_CONFIRMED",
            business_type="EXCEL_IMPORT",
            business_id=str(job.id),
            reason="queued_for_hr05_import_worker",
        )
        return job


def _claim_commit(*, tenant_id: int, job_id):
    from django.utils import timezone
    from hr_onboarding.models import HrOnboardingImportJob

    with transaction.atomic():
        job = HrOnboardingImportJob.objects.select_for_update().filter(
            tenant_id=int(tenant_id), id=job_id
        ).first()
        if job is None:
            raise ExcelImportStateError("EXCEL_JOB_NOT_FOUND", "导入作业不存在")
        if job.status == HrOnboardingImportJob.Status.COMPLETED:
            return job, False
        if job.status == HrOnboardingImportJob.Status.VALIDATION_FAILED:
            raise ExcelImportStateError("EXCEL_VALIDATION_FAILED", "导入文件存在校验错误，请先下载错误表")
        if job.status == HrOnboardingImportJob.Status.FAILED:
            raise ExcelImportStateError("EXCEL_COMMIT_FAILED", "导入作业已失败，请查看错误表后重新上传")
        if job.status == HrOnboardingImportJob.Status.COMMITTING and job.commit_started_at:
            age = (timezone.now() - job.commit_started_at).total_seconds()
            if age < COMMIT_STALE_SECONDS:
                raise ExcelImportStateError("EXCEL_COMMIT_IN_PROGRESS", "导入作业正在执行，请勿重复确认")
        if job.status not in {
            HrOnboardingImportJob.Status.READY_TO_COMMIT,
            HrOnboardingImportJob.Status.COMMITTING,
        }:
            raise ExcelImportStateError("EXCEL_JOB_STATE_INVALID", f"当前状态 {job.status} 不可确认导入")
        job.status = HrOnboardingImportJob.Status.COMMITTING
        job.commit_started_at = timezone.now()
        job.save(update_fields=["status", "commit_started_at", "updated_at"])
        return job, True


def commit_persisted_import(*, tenant_id: int, job_id, actor_user_id: int | None):
    """Idempotently commit valid rows through CaseService; safe across workers/retries."""

    from hr_onboarding.models import (
        HrOnboardingAuditEvent,
        HrOnboardingImportJob,
        HrOnboardingImportRow,
    )
    from hr_onboarding.services.case_service import CaseService

    job, claimed = _claim_commit(tenant_id=tenant_id, job_id=job_id)
    if not claimed:
        return job

    service = CaseService(tenant_id=int(tenant_id), actor_user_id=actor_user_id)
    for row in job.rows.filter(status=HrOnboardingImportRow.Status.VALID).order_by("row_no").iterator(chunk_size=200):
        payload = dict(row.payload_json or {})
        source_type = str(payload.get("source_type") or "LEGACY_MIGRATION")
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            source_id = f"excel:{job.id}:{row.row_no}"
        request = {
            "source_type": source_type,
            "source_id": source_id,
            "legal_name": str(payload.get("legal_name") or ""),
            "employment_type": str(payload.get("employment_type") or "FULL_TIME"),
            "staff_category": str(payload.get("staff_category") or "TEACHER"),
            "expected_report_date": payload.get("expected_report_date") or None,
        }
        try:
            result = service.create_case_from_handoff(
                request,
                idempotency_key=f"hr05-excel:{job.id}:{row.row_no}",
            )
            # A successful same-row idempotency replay means this import row
            # already created the authority before a crash; keep it CREATED.
            row.status = HrOnboardingImportRow.Status.CREATED
            row.result_ref = str(result.get("case_id") or "")[:128]
            row.error_json = []
        except Exception as exc:  # noqa: BLE001 - persist a bounded business failure, not traceback
            row.status = HrOnboardingImportRow.Status.FAILED
            row.result_ref = ""
            row.error_json = [
                {
                    "field": "commit",
                    "message": str(exc)[:500] or type(exc).__name__,
                }
            ]
        row.processed_at = timezone.now()
        row.save(update_fields=["status", "result_ref", "error_json", "processed_at"])

    counts = {
        item["status"]: item["count"]
        for item in job.rows.values("status").annotate(count=Count("id"))
    }
    created = int(counts.get(HrOnboardingImportRow.Status.CREATED, 0))
    skipped = int(counts.get(HrOnboardingImportRow.Status.SKIPPED, 0))
    failed = int(counts.get(HrOnboardingImportRow.Status.FAILED, 0))
    now = timezone.now()
    final_status = (
        HrOnboardingImportJob.Status.FAILED
        if failed
        else HrOnboardingImportJob.Status.COMPLETED
    )
    with transaction.atomic():
        locked = HrOnboardingImportJob.objects.select_for_update().get(
            tenant_id=int(tenant_id), id=job.id
        )
        locked.status = final_status
        locked.created_count = created
        locked.skipped_count = skipped
        locked.failed_count = failed
        locked.error_count = locked.rows.filter(
            status__in=[
                HrOnboardingImportRow.Status.INVALID,
                HrOnboardingImportRow.Status.FAILED,
            ]
        ).count()
        locked.result_json = {
            "created": created,
            "skipped": skipped,
            "failed": failed,
        }
        locked.completed_at = now
        locked.save(
            update_fields=[
                "status", "created_count", "skipped_count", "failed_count",
                "error_count", "result_json", "completed_at", "updated_at",
            ]
        )
        HrOnboardingAuditEvent.objects.create(
            tenant_id=int(tenant_id),
            actor_user_id=actor_user_id,
            action=("EXCEL_IMPORT_COMPLETED" if not failed else "EXCEL_IMPORT_FAILED"),
            business_type="EXCEL_IMPORT",
            business_id=str(locked.id),
            reason=f"created={created}; skipped={skipped}; failed={failed}",
        )
    return locked
