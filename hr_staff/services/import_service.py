"""
hr_staff/services/import_service.py —— 导入 staging 服务（总册 §24）。

流程：上传 → 解析到 staging → 格式/字典/tenant/去重校验 → 预览 → 显式 commit。
当前 Web 入口采用有上限的同步 commit；每行独立事务 + checkpoint，禁止用一个
超大事务包住整份导入，也禁止把“已提交/部分失败”任务重复执行。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_staff.constants import ImportJobStatus
from hr_staff.models import HrImportIssue, HrImportJob, HrImportRow

logger = logging.getLogger(__name__)

COMMIT_LEASE_SECONDS = 30 * 60
COMMIT_HEARTBEAT_EVERY_ROWS = 25


class ImportStateConflict(Exception):
    code = "IMPORT_STATE_CONFLICT"


class ImportService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    # ------------------------------------------------------------------
    # Job 生命周期
    # ------------------------------------------------------------------
    def create_job(self, *, template_key: str, original_filename: str = "") -> HrImportJob:
        return HrImportJob.objects.create(
            tenant_id=self.tenant_id,
            template_key=template_key,
            original_filename=(original_filename or "")[:255],
        )

    def job_for_id(self, job_id) -> Optional[HrImportJob]:
        return HrImportJob.objects.filter(tenant_id=self.tenant_id, id=job_id).first()

    def parse_rows(self, job: HrImportJob, rows: list[dict]):
        """把上传行解析进 staging（不写 authority）。"""
        if job.tenant_id != self.tenant_id:
            raise ImportStateConflict("导入任务不属于当前学校")
        if job.status != ImportJobStatus.UPLOADED or job.rows.exists():
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
                    data_json=row,
                )
                for idx, row in enumerate(rows, start=2)
            ],
            batch_size=500,
        )
        return job

    def validate_rows(self, job: HrImportJob, row_validator) -> HrImportJob:
        """逐行校验；不通过标记 is_valid=False + 写精确失败行。"""
        if job.tenant_id != self.tenant_id:
            raise ImportStateConflict("导入任务不属于当前学校")
        if job.status not in (ImportJobStatus.VALIDATING, ImportJobStatus.UPLOADED):
            raise ImportStateConflict(f"当前状态 {job.status} 不允许重新校验")

        for row in job.rows.all().iterator(chunk_size=500):
            errors = row_validator(dict(row.data_json or {}))
            if errors:
                row.is_valid = False
                row.error_summary = "; ".join(errors.values())[:500]
                row.save(update_fields=["is_valid", "error_summary"])
                HrImportIssue.objects.bulk_create(
                    [
                        HrImportIssue(
                            tenant_id=self.tenant_id,
                            job_id=job,
                            row_id=row,
                            row_no=row.row_no,
                            field_code=field,
                            error_code="VALIDATION_ERROR",
                            message=str(message)[:500],
                        )
                        for field, message in errors.items()
                    ]
                )
        valid = job.rows.filter(is_valid=True).count()
        failed = job.rows.filter(is_valid=False).count()
        job.valid_rows = valid
        job.failed_rows = failed
        job.status = (
            ImportJobStatus.READY_TO_COMMIT
            if valid > 0
            else ImportJobStatus.VALIDATION_FAILED
        )
        job.save(update_fields=["valid_rows", "failed_rows", "status"])
        return job

    # ------------------------------------------------------------------
    # Commit（逐行独立事务 + checkpoint；同人员多表由 row_applier 内部原子）
    # ------------------------------------------------------------------
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
            # Backward-compatible recovery for jobs left COMMITTING before the
            # lease fields existed. updated_at is the best durable heartbeat.
            heartbeat = job.updated_at
        if heartbeat is None:
            return True
        return heartbeat <= now - timedelta(seconds=COMMIT_LEASE_SECONDS)

    def _save_commit_heartbeat(self, locked, checkpoint):
        checkpoint["commit_heartbeat_at"] = timezone.now().isoformat()
        checkpoint["commit_actor_user_id"] = self.actor_user_id
        locked.checkpoint = checkpoint
        locked.save(update_fields=["checkpoint"])

    def commit(self, job: HrImportJob, row_applier, batch_size: int = 100) -> dict:
        """提交 READY_TO_COMMIT job，并可安全恢复失联的 COMMITTING job。

        ``row_applier`` 收到 staging 数据副本，并附加两个仅服务端生成的保留键：
        ``_import_job_id`` / ``_import_row_no``。它们形成稳定、job-scoped 的业务来源
        id，避免不同导入任务把 ``import-row-0`` 当成同一来源。

        每一行的 authority 写入与 ``commit_status=COMMITTED`` 在同一个数据库事务
        内完成，因此进程崩溃不会留下“事实已写、staging 未记账”的半行。COMMITTING
        状态用 30 分钟持久 heartbeat 租约防止并发执行；租约过期后可从未提交行恢复。
        """
        now = timezone.now()
        with transaction.atomic():
            locked = HrImportJob.objects.select_for_update().get(
                tenant_id=self.tenant_id,
                id=job.id,
            )
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
            checkpoint["commit_heartbeat_at"] = now.isoformat()
            checkpoint["commit_actor_user_id"] = self.actor_user_id
            locked.status = ImportJobStatus.COMMITTING
            locked.checkpoint = checkpoint
            locked.save(update_fields=["status", "checkpoint"])

        processed = 0
        valid_rows = locked.rows.filter(is_valid=True).order_by("row_no")
        for row in valid_rows.iterator(chunk_size=max(1, min(batch_size, 500))):
            if row.commit_status == "COMMITTED":
                continue
            try:
                row_payload = dict(row.data_json or {})
                row_payload["_import_job_id"] = str(locked.id)
                row_payload["_import_row_no"] = row.row_no
                with transaction.atomic():
                    row_applier(row_payload, checkpoint)
                    row.commit_status = "COMMITTED"
                    row.save(update_fields=["commit_status"])
                checkpoint["last_committed_row"] = row.row_no
            except Exception as exc:
                # Do not persist raw database/service exception text into a row
                # ledger that is returned to HR users. It can contain SQL object
                # names, infrastructure details or uploaded identity values.
                logger.warning(
                    "HR03 import row commit failed tenant=%s job=%s row=%s class=%s",
                    self.tenant_id,
                    locked.id,
                    row.row_no,
                    exc.__class__.__name__,
                )
                safe_message = self._safe_commit_error(exc)
                with transaction.atomic():
                    row.commit_status = "FAILED"
                    row.is_valid = False
                    row.error_summary = safe_message[:500]
                    row.save(update_fields=["commit_status", "is_valid", "error_summary"])
                    HrImportIssue.objects.create(
                        tenant_id=self.tenant_id,
                        job_id=locked,
                        row_id=row,
                        row_no=row.row_no,
                        error_code="COMMIT_FAILED",
                        message=safe_message[:500],
                    )
            processed += 1
            if processed % COMMIT_HEARTBEAT_EVERY_ROWS == 0:
                self._save_commit_heartbeat(locked, checkpoint)

        # Recount durable row state rather than relying on counters from this
        # process. That makes stale-lease resume and idempotent replay correct.
        committed = locked.rows.filter(commit_status="COMMITTED").count()
        failed = locked.rows.filter(is_valid=False).count()
        checkpoint["committed_rows"] = committed
        checkpoint["failed_rows"] = failed
        checkpoint["commit_finished_at"] = timezone.now().isoformat()
        checkpoint.pop("commit_heartbeat_at", None)
        checkpoint.pop("commit_actor_user_id", None)

        locked.checkpoint = checkpoint
        locked.committed_by = self.actor_user_id
        locked.committed_at = timezone.now()
        locked.failed_rows = failed
        locked.status = (
            ImportJobStatus.COMPLETED
            if failed == 0
            else ImportJobStatus.PARTIAL_FAILED
        )
        locked.save(
            update_fields=[
                "checkpoint",
                "committed_by",
                "committed_at",
                "failed_rows",
                "status",
            ]
        )
        return self._result_for_job(locked)

    @staticmethod
    def _safe_commit_error(exc: Exception) -> str:
        """Return an actionable but non-secret error suitable for HR ledgers."""
        text = str(exc)
        lowered = text.lower()
        if (
            "document" in lowered
            or "identity" in lowered
            or "证件" in text
            or "身份证" in text
        ):
            return f"{exc.__class__.__name__}: 身份信息校验失败，请检查该行证件字段"

        # These messages are generated locally by StaffMasterRowApplier and do
        # not echo uploaded values or backend internals.
        if text == "legal_name 必填" or text.startswith("无效日期格式"):
            return f"{exc.__class__.__name__}: {text}"[:500]

        return f"{exc.__class__.__name__}: 导入写入失败，请检查该行数据或联系管理员"

    @staticmethod
    def _result_for_job(job: HrImportJob) -> dict:
        committed = job.rows.filter(commit_status="COMMITTED").count()
        failed = job.rows.filter(is_valid=False).count()
        return {"committed": committed, "failed": failed, "total": job.total_rows}


class StaffMasterRowApplier:
    """真实 row_applier：一行 = Person + StaffMaster + Relationship + Assignment 原子写。"""

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

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

        person = PersonIdentityService().create_person_with_identity(
            tenant_id=self.tenant_id,
            legal_name=legal_name,
            gender_code=(row_data.get("gender_code") or "").strip() or None,
            birth_date=self._parse_date(row_data.get("birth_date")),
            document_number=(row_data.get("document_number") or "").strip() or None,
        )
        staff = StaffMasterService().create_staff(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=(row_data.get("staff_no") or "").strip() or None,
            staff_category_code=(row_data.get("staff_category_code") or "TEACHER").strip(),
            source="MIGRATED",
        )
        # Default business date must follow the configured school timezone, not
        # the container host's calendar date around midnight.
        effective_from = self._parse_date(row_data.get("effective_from")) or timezone.localdate()
        job_id = str(row_data.get("_import_job_id") or "direct")
        row_no = row_data.get("_import_row_no")
        if row_no is None:
            row_no = int(checkpoint.get("last_committed_row", 0) or 0) + 1
        source_business_id = f"import:{job_id}:row:{row_no}"
        rel = EmploymentService(self.tenant_id).start_relationship(
            staff_id=staff,
            relationship_type=(row_data.get("relationship_type") or "REGULAR_EMPLOYMENT").strip(),
            effective_from=effective_from,
            source_business_type="MIGRATION_VERIFIED",
            source_business_id=source_business_id,
        )
        legacy_dept = row_data.get("legacy_department_id")
        AssignmentService(
            self.tenant_id, audit_actor_user_id=self.actor_user_id
        ).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=effective_from,
            organization_id=None,
            legacy_department_id=int(legacy_dept) if legacy_dept else None,
            source_business_type="MIGRATION_VERIFIED",
            source_business_id=source_business_id,
        )
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
        raise ValueError("无效日期格式，要求 YYYY-MM-DD、YYYY/MM/DD 或 DD/MM/YYYY")
