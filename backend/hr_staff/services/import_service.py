"""
hr_staff/services/import_service.py —— 导入 staging 服务（总册 §24）。

流程：上传 → 解析到 staging → 格式/字典/tenant/去重校验 → 预览 → 显式 commit。
当前 Web 入口采用有上限的同步 commit；每行独立事务 + checkpoint，禁止用一个
超大事务包住整份导入，也禁止把“已提交/部分失败”任务重复执行。
"""

from __future__ import annotations

import logging
import json
import uuid
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_staff.constants import ImportJobStatus
from hr_staff.models import HrImportIssue, HrImportJob, HrImportRow

logger = logging.getLogger(__name__)

COMMIT_LEASE_SECONDS = 30 * 60
COMMIT_BATCH_LIMIT = 100
COMMIT_TIME_BUDGET_SECONDS = 8


class ImportStateConflict(Exception):
    code = "IMPORT_STATE_CONFLICT"


class ImportService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def create_job(self, *, template_key: str, original_filename: str = "") -> HrImportJob:
        return HrImportJob.objects.create(
            tenant_id=self.tenant_id,
            template_key=template_key,
            original_filename=(original_filename or "")[:255],
        )

    def job_for_id(self, job_id) -> Optional[HrImportJob]:
        return HrImportJob.objects.filter(tenant_id=self.tenant_id, id=job_id).first()

    @transaction.atomic
    def parse_rows(self, job: HrImportJob, rows: list[dict]):
        """把上传行解析进 staging（不写 authority）。"""
        if job.tenant_id != self.tenant_id:
            raise ImportStateConflict("导入任务不属于当前学校")
        locked = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, id=job.pk)
        if locked.status != ImportJobStatus.UPLOADED or locked.rows.exists():
            raise ImportStateConflict("导入任务已经解析，禁止重复写入 staging")
        job.status = ImportJobStatus.VALIDATING
        job.total_rows = len(rows)
        job.save(update_fields=["status", "total_rows"])
        HrImportRow.objects.bulk_create(
            [
                HrImportRow(
                    tenant_id=self.tenant_id,
                    job_id=job,
                    row_no=idx,
                    data_json=self._encode_row(job, idx, row),
                )
                for idx, row in enumerate(rows, start=2)
            ],
            batch_size=500,
        )
        return job

    @transaction.atomic
    def validate_rows(self, job: HrImportJob, row_validator, *, row_enricher=None) -> HrImportJob:
        """逐行校验；不通过标记 is_valid=False + 写精确失败行。"""
        if job.tenant_id != self.tenant_id:
            raise ImportStateConflict("导入任务不属于当前学校")
        locked = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, id=job.pk)
        if locked.status not in (ImportJobStatus.VALIDATING, ImportJobStatus.UPLOADED):
            raise ImportStateConflict(f"当前状态 {job.status} 不允许重新校验")

        # Staging is not a formal business model. Batch preview changes while
        # keeping the surrounding job transaction atomic.
        dirty, issues = [], []

        def flush():
            if dirty:
                HrImportRow.objects.filter(tenant_id=self.tenant_id, job_id=job).bulk_update(
                    dirty, ["is_valid", "error_summary", "data_json"], batch_size=250
                )
                dirty.clear()
            if issues:
                HrImportIssue.objects.bulk_create(issues, batch_size=250)
                issues.clear()

        job.issues.filter(tenant_id=self.tenant_id, error_code="VALIDATION_ERROR").delete()
        for row in job.rows.filter(tenant_id=self.tenant_id).order_by("row_no").iterator(chunk_size=250):
            payload = self._decode_row(row)
            errors = row_validator(payload)
            row.is_valid = not bool(errors)
            row.error_summary = "; ".join(str(message) for message in errors.values())[:500]
            if errors:
                issues.extend(
                    HrImportIssue(
                        tenant_id=self.tenant_id, job_id=job, row_id=row,
                        row_no=row.row_no, field_code=field,
                        error_code="VALIDATION_ERROR", message=str(message)[:500],
                    )
                    for field, message in errors.items()
                )
            elif row_enricher is not None:
                row.data_json = {**row.data_json, **row_enricher(payload)}
            dirty.append(row)
            if len(dirty) >= 250:
                flush()
        flush()
        valid = job.rows.filter(tenant_id=self.tenant_id, is_valid=True).count()
        failed = job.rows.filter(tenant_id=self.tenant_id, is_valid=False).count()
        job.valid_rows = valid
        job.failed_rows = failed
        job.status = ImportJobStatus.READY_TO_COMMIT if valid > 0 else ImportJobStatus.VALIDATION_FAILED
        job.save(update_fields=["valid_rows", "failed_rows", "status"])
        return job

    @staticmethod
    def _checkpoint_time(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    @classmethod
    def _commit_lease_is_stale(cls, job, checkpoint, now):
        heartbeat = cls._checkpoint_time(checkpoint.get("commit_heartbeat_at"))
        if heartbeat is None:
            heartbeat = cls._checkpoint_time(checkpoint.get("commit_started_at"))
        if heartbeat is None:
            heartbeat = job.updated_at
        if heartbeat is None:
            return True
        return heartbeat <= now - timedelta(seconds=COMMIT_LEASE_SECONDS)

    def commit(self, job: HrImportJob, row_applier, batch_size: int = 100) -> dict:
        """Fence every row by a short job lock; authority and row state commit together."""
        started = time.monotonic()
        now = timezone.now()
        token = uuid.uuid4().hex
        with transaction.atomic():
            locked = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, id=job.id)
            if locked.status in (ImportJobStatus.COMPLETED, ImportJobStatus.PARTIAL_FAILED):
                return self._result_for_job(locked)
            checkpoint = dict(locked.checkpoint or {})
            if locked.status == ImportJobStatus.COMMITTING:
                if not self._commit_lease_is_stale(locked, checkpoint, now):
                    raise ImportStateConflict("导入任务正在提交，请勿重复提交")
                checkpoint["resumed_at"] = now.isoformat()
                checkpoint["resume_count"] = int(checkpoint.get("resume_count", 0) or 0) + 1
            elif locked.status != ImportJobStatus.READY_TO_COMMIT:
                raise ImportStateConflict(f"当前状态 {locked.status} 不允许提交")
            checkpoint.setdefault("commit_started_at", now.isoformat())
            checkpoint.update(commit_token=token, commit_heartbeat_at=now.isoformat(),
                              commit_actor_user_id=self.actor_user_id)
            locked.status = ImportJobStatus.COMMITTING
            locked.checkpoint = checkpoint
            locked.save(update_fields=["status", "checkpoint", "updated_at"])

        identifiers = list(locked.rows.filter(tenant_id=self.tenant_id, is_valid=True, commit_status="PENDING")
                           .order_by("row_no").values_list("pk", flat=True)[:max(1, min(batch_size, COMMIT_BATCH_LIMIT))])
        for index, row_id in enumerate(identifiers):
            if index and time.monotonic() - started >= COMMIT_TIME_BUDGET_SECONDS:
                break
            with transaction.atomic():
                current = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, pk=job.pk)
                checkpoint = dict(current.checkpoint or {})
                self._assert_executor(current, checkpoint, token)
                row = HrImportRow.objects.select_for_update().get(tenant_id=self.tenant_id, job_id_id=job.pk, pk=row_id)
                if row.commit_status == "COMMITTED" or not row.is_valid:
                    continue
                try:
                    # Catch outside the savepoint. A failure rolls back the
                    # complete person, while the outer job lock remains held.
                    with transaction.atomic():
                        payload = self._decode_row(row)
                        payload.update(_import_job_id=str(job.pk), _import_row_no=row.row_no)
                        result = row_applier(payload, checkpoint)
                        row.commit_status = "COMMITTED"
                        if getattr(result, "staff_no", None):
                            row.data_json = {**row.data_json, "_result_staff_id": str(result.pk)}
                        row.save(update_fields=["commit_status", "data_json"])
                    checkpoint["last_committed_row"] = row.row_no
                except Exception as exc:
                    logger.warning("HR03 import row failed tenant=%s job=%s row=%s class=%s",
                                   self.tenant_id, job.pk, row.row_no, exc.__class__.__name__)
                    safe_message = self._safe_commit_error(exc)
                    row.commit_status, row.is_valid, row.error_summary = "FAILED", False, safe_message[:500]
                    row.save(update_fields=["commit_status", "is_valid", "error_summary"])
                    HrImportIssue.objects.create(tenant_id=self.tenant_id, job_id=current, row_id=row,
                        row_no=row.row_no, field_code=getattr(exc, "field", "")[:64],
                        error_code="COMMIT_FAILED", message=safe_message[:500])
                checkpoint["commit_heartbeat_at"] = timezone.now().isoformat()
                current.checkpoint = checkpoint
                current.save(update_fields=["checkpoint", "updated_at"])

        with transaction.atomic():
            current = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, pk=job.pk)
            checkpoint = dict(current.checkpoint or {})
            self._assert_executor(current, checkpoint, token)
            result = self._result_for_job(current)
            pending = current.rows.filter(tenant_id=self.tenant_id, is_valid=True, commit_status="PENDING").count()
            if pending:
                for key in ("commit_token", "commit_heartbeat_at", "commit_actor_user_id"):
                    checkpoint.pop(key, None)
                checkpoint.update(committed_rows=result["committed"], failed_rows=result["failed"])
                current.checkpoint, current.status = checkpoint, ImportJobStatus.READY_TO_COMMIT
                current.failed_rows = result["failed"]
                current.save(update_fields=["checkpoint", "status", "failed_rows", "updated_at"])
                return {**result, "pending": pending}
            checkpoint.update(committed_rows=result["committed"], failed_rows=result["failed"],
                              commit_finished_at=timezone.now().isoformat())
            for key in ("commit_token", "commit_heartbeat_at", "commit_actor_user_id"):
                checkpoint.pop(key, None)
            current.checkpoint = checkpoint
            current.committed_by, current.committed_at = self.actor_user_id, timezone.now()
            current.failed_rows = result["failed"]
            current.status = ImportJobStatus.COMPLETED if not result["failed"] else ImportJobStatus.PARTIAL_FAILED
            current.save(update_fields=["checkpoint", "committed_by", "committed_at", "failed_rows", "status", "updated_at"])
            from hr_staff.services.audit_service import write_audit_event
            write_audit_event(tenant_id=self.tenant_id, actor_user_id=self.actor_user_id,
                              action="StaffImportCompleted", business_type="STAFF_IMPORT", business_id=str(job.pk),
                              reason=f"committed={result['committed']} failed={result['failed']}")
            return result

    @staticmethod
    def _assert_executor(job, checkpoint, token):
        if job.status != ImportJobStatus.COMMITTING or checkpoint.get("commit_token") != token:
            raise ImportStateConflict("提交执行权已变化，请重新读取任务状态")

    def _encode_row(self, job, row_no, source):
        from hr_staff.services.crypto import encrypt_document_number
        payload = dict(source)
        document = payload.pop("document_number", "")
        if document:
            envelope = json.dumps({"tenant": self.tenant_id, "job": str(job.pk), "row": row_no, "value": document})
            payload["_document_ciphertext"] = encrypt_document_number(self.tenant_id, envelope)
        return payload

    def _decode_row(self, row):
        from hr_staff.services.crypto import decrypt_document_number
        from hr_staff.services.import_validation import ImportRowError
        payload = dict(row.data_json or {})
        ciphertext = payload.pop("_document_ciphertext", None)
        if ciphertext:
            try:
                envelope = json.loads(decrypt_document_number(ciphertext))
                if (envelope["tenant"] != self.tenant_id or envelope["job"] != str(row.job_id_id)
                        or envelope["row"] != row.row_no):
                    raise ValueError
                payload["document_number"] = envelope["value"]
            except (ValueError, TypeError, KeyError):
                raise ImportRowError("document_number", "证件暂存数据无法安全读取，请重新上传") from None
        return payload

    @staticmethod
    def _safe_commit_error(exc: Exception) -> str:
        """Return an actionable but non-secret error suitable for HR ledgers."""
        from hr_staff.services.import_validation import ImportRowError
        if isinstance(exc, ImportRowError):
            return exc.message
        text = str(exc)
        lowered = text.lower()
        if "document" in lowered or "identity" in lowered or "证件" in text or "身份证" in text:
            return f"{exc.__class__.__name__}: 身份信息校验失败，请检查该行证件字段"
        if text == "legal_name 必填" or text.startswith("无效日期格式"):
            return f"{exc.__class__.__name__}: {text}"[:500]
        return f"{exc.__class__.__name__}: 导入写入失败，请检查该行数据或联系管理员"

    @staticmethod
    def _result_for_job(job: HrImportJob) -> dict:
        committed = job.rows.filter(tenant_id=job.tenant_id, commit_status="COMMITTED").count()
        failed = job.rows.filter(tenant_id=job.tenant_id, is_valid=False).count()
        return {"committed": committed, "failed": failed, "total": job.total_rows}


class StaffMasterRowApplier:
    """One verified row atomically creates Person, Staff, relationship and assignment."""

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None, *, today=None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.today = today or timezone.localdate()

    @transaction.atomic
    def __call__(self, row_data: dict, checkpoint: dict):
        from hr_staff.constants import AssignmentType
        from hr_staff.services.assignment_service import AssignmentService
        from hr_staff.services.employment_service import EmploymentService
        from hr_staff.services.person_identity_service import PersonIdentityService
        from hr_staff.services.staff_master_service import StaffMasterService

        legal_name = (row_data.get("legal_name") or "").strip()
        if not legal_name:
            raise ValueError("legal_name 必填")
        references = None
        if row_data.get("organization_code") or row_data.get("position_code"):
            from hr_staff.services.import_validation import basic_errors, ImportRowError, StructureReferences
            errors = basic_errors(row_data, today=self.today)
            if errors:
                field, message = next(iter(errors.items()))
                raise ImportRowError(field, message)
            references = StructureReferences(self.tenant_id, [row_data], lock=True).resolve(row_data)

        person = PersonIdentityService().create_person_with_identity(
            tenant_id=self.tenant_id, legal_name=legal_name,
            audit_actor_user_id=self.actor_user_id,
            gender_code=(row_data.get("gender_code") or "").strip() or None,
            birth_date=self._parse_date(row_data.get("birth_date")),
            document_number=(row_data.get("document_number") or "").strip() or None,
        )
        staff = StaffMasterService().create_staff(
            tenant_id=self.tenant_id, person_id=person,
            staff_no=(row_data.get("staff_no") or "").strip() or None,
            staff_category_code=(row_data.get("staff_category_code") or "TEACHER").strip(),
            source="MIGRATED", audit_actor_user_id=self.actor_user_id,
        )
        effective_from = self._parse_date(row_data.get("effective_from")) or self.today
        job_id = str(row_data.get("_import_job_id") or "direct")
        row_no = row_data.get("_import_row_no")
        if row_no is None:
            row_no = int(checkpoint.get("last_committed_row", 0) or 0) + 1
        source_business_id = f"import:{job_id}:row:{row_no}"
        rel = EmploymentService(self.tenant_id, audit_actor_user_id=self.actor_user_id).start_relationship(
            staff_id=staff,
            relationship_type=(row_data.get("relationship_type") or "REGULAR_EMPLOYMENT").strip(),
            effective_from=effective_from,
            source_business_type="MIGRATION_VERIFIED", source_business_id=source_business_id,
        )
        legacy_dept = row_data.get("legacy_department_id")
        AssignmentService(self.tenant_id, audit_actor_user_id=self.actor_user_id).create_assignment(
            employment_relationship_id=rel, assignment_type=AssignmentType.PRIMARY,
            effective_from=effective_from,
            organization_id=references[0] if references else None,
            position_id=references[1] if references else None,
            post_catalog_id=references[2] if references else None,
            fte=Decimal(row_data.get("fte") or "1.00"),
            legacy_department_id=int(legacy_dept) if legacy_dept and not references else None,
            source_business_type="MIGRATION_VERIFIED", source_business_id=source_business_id,
        )
        from hr_staff.services.audit_service import write_audit_event
        write_audit_event(tenant_id=self.tenant_id, actor_user_id=self.actor_user_id,
                          staff_id=staff.pk, action="StaffImportRowCommitted",
                          business_type="STAFF_IMPORT", business_id=source_business_id)
        return staff

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(str(value).strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError("无效日期格式，支持 YYYY-MM-DD、YYYY/MM/DD 或 DD/MM/YYYY")
