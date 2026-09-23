"""
hr_staff/services/import_service.py —— 导入 staging 服务（总册 §24）。

流程：上传 → 解析到 staging → 格式/字典/tenant/去重校验 → 预览 → 显式 commit。
当前 Web 入口采用有上限的同步 commit；每行独立事务 + checkpoint，禁止用一个
超大事务包住整份导入，也禁止把“已提交/部分失败”任务重复执行。
"""

from __future__ import annotations

import logging
from uuid import uuid4
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_staff.constants import ImportJobStatus
from hr_staff.models import HrImportIssue, HrImportJob, HrImportRow
from hr_staff.services.import_validation import (
    ImportRowValidationError,
    parse_import_date,
    validate_staff_import_row_for_commit,
)

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
                    row_no=row.get("_source_row_no", idx),
                    data_json={k: v for k, v in row.items() if k != "_source_row_no"},
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

    def _owned_job(self, job_id, token):
        locked = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, id=job_id)
        if locked.status != ImportJobStatus.COMMITTING or (locked.checkpoint or {}).get("commit_token") != token:
            raise ImportStateConflict("本次提交已被安全接管，请重新查询服务器结果")
        return locked

    def commit(self, job: HrImportJob, row_applier, batch_size: int = 100) -> dict:
        """Claim with a fencing token; lock owner + row for each atomic write.

        The token is checked inside every row transaction. A process paused
        beyond the lease cannot keep writing after a new owner takes over.
        Authority writes, readback and COMMITTED ledger share one transaction.
        """
        now, token = timezone.now(), str(uuid4())
        with transaction.atomic():
            locked = HrImportJob.objects.select_for_update().get(tenant_id=self.tenant_id, id=job.id)
            if locked.status in (ImportJobStatus.COMPLETED, ImportJobStatus.PARTIAL_FAILED):
                return self._result_for_job(locked)
            checkpoint = dict(locked.checkpoint or {})
            if locked.status == ImportJobStatus.COMMITTING:
                if not self._commit_lease_is_stale(locked, checkpoint, now):
                    raise ImportStateConflict("导入正在提交，请点击重新查询结果，不要再次提交")
                checkpoint["resumed_at"] = now.isoformat()
                checkpoint["resume_count"] = int(checkpoint.get("resume_count", 0) or 0) + 1
            elif locked.status != ImportJobStatus.READY_TO_COMMIT:
                raise ImportStateConflict(f"当前状态 {locked.status} 不允许提交")
            checkpoint.setdefault("commit_started_at", now.isoformat())
            checkpoint.update(commit_token=token, commit_heartbeat_at=now.isoformat(), commit_actor_user_id=self.actor_user_id)
            locked.status, locked.checkpoint = ImportJobStatus.COMMITTING, checkpoint
            locked.save(update_fields=["status", "checkpoint", "updated_at"])

        row_ids = list(locked.rows.filter(tenant_id=self.tenant_id, is_valid=True)
                       .exclude(commit_status="COMMITTED").order_by("row_no").values_list("id", flat=True))
        for row_id in row_ids:
            with transaction.atomic():
                locked = self._owned_job(job.id, token)
                checkpoint = dict(locked.checkpoint or {})
                row = HrImportRow.objects.select_for_update().get(id=row_id, tenant_id=self.tenant_id, job_id=locked)
                if row.commit_status == "COMMITTED" or not row.is_valid:
                    continue
                row_payload = dict(row.data_json or {})
                row_payload.update(_import_job_id=str(locked.id), _import_row_no=row.row_no)
                try:
                    # Savepoint rollback removes Person/Staff/Relationship/Assignment
                    # together before persisting a safe failure ledger.
                    with transaction.atomic():
                        result = row_applier(row_payload, checkpoint)
                        result_ref = ""
                        if getattr(row_applier, "produces_staff_master", False):
                            from hr_staff.models import HrStaffMaster
                            if result is None or not HrStaffMaster.objects.filter(
                                tenant_id=self.tenant_id, pk=result.pk, person_id__tenant_id=self.tenant_id
                            ).exists():
                                raise ValueError("AUTHORITY_READBACK_MISSING")
                            result_ref = str(result.pk)
                            # This audit row is deliberately inside the same savepoint as
                            # Person/Staff/Employment/Assignment and the import-row ledger.
                            # If audit persistence fails, the complete authority write rolls back.
                            from hr_staff.services.audit_service import write_audit_event
                            write_audit_event(
                                tenant_id=self.tenant_id,
                                action="IMPORT_ROW_COMMITTED",
                                actor_user_id=self.actor_user_id,
                                staff_id=result.pk,
                                business_type="HR03_IMPORT_ROW",
                                business_id=f"{locked.id}:{row.row_no}",
                                after_snapshot_ref=f"staff:{result.pk}",
                                reason="人员/主档/聘用/任职已完成事务内回读",
                                source="HR03",
                            )
                        row.commit_status, row.result_ref = "COMMITTED", result_ref
                        row.error_summary = ""
                        row.save(update_fields=["commit_status", "result_ref", "error_summary"])
                except Exception as exc:
                    logger.warning("HR03 import row failed tenant=%s job=%s row=%s class=%s",
                                   self.tenant_id, locked.id, row.row_no, exc.__class__.__name__)
                    safe_message = self._safe_commit_error(exc)
                    row.commit_status, row.is_valid, row.result_ref = "FAILED", False, ""
                    row.error_summary = safe_message[:500]
                    row.save(update_fields=["commit_status", "is_valid", "error_summary", "result_ref"])
                    if isinstance(exc, ImportRowValidationError):
                        HrImportIssue.objects.bulk_create([
                            HrImportIssue(
                                tenant_id=self.tenant_id, job_id=locked, row_id=row, row_no=row.row_no,
                                field_code=field, error_code="COMMIT_VALIDATION_ERROR", message=str(message)[:500]
                            )
                            for field, message in exc.errors.items()
                        ])
                    else:
                        HrImportIssue.objects.create(tenant_id=self.tenant_id, job_id=locked, row_id=row,
                            row_no=row.row_no, error_code="COMMIT_FAILED", message=safe_message[:500])
                else:
                    checkpoint["last_committed_row"] = row.row_no
                checkpoint["commit_heartbeat_at"] = timezone.now().isoformat()
                locked.checkpoint = checkpoint
                locked.save(update_fields=["checkpoint", "updated_at"])

        with transaction.atomic():
            locked = self._owned_job(job.id, token)
            if locked.rows.filter(is_valid=True).exclude(commit_status="COMMITTED").exists():
                raise ImportStateConflict("仍有行尚未处理完成，请重新查询结果")
            committed = locked.rows.filter(commit_status="COMMITTED").count()
            failed = locked.rows.filter(is_valid=False).count()
            checkpoint = dict(locked.checkpoint or {})
            checkpoint.update(committed_rows=committed, failed_rows=failed, commit_finished_at=timezone.now().isoformat())
            for key in ("commit_heartbeat_at", "commit_actor_user_id", "commit_token"):
                checkpoint.pop(key, None)
            locked.checkpoint, locked.committed_by = checkpoint, self.actor_user_id
            locked.committed_at, locked.failed_rows = timezone.now(), failed
            locked.status = ImportJobStatus.COMPLETED if failed == 0 else ImportJobStatus.PARTIAL_FAILED
            locked.save(update_fields=["checkpoint", "committed_by", "committed_at", "failed_rows", "status", "updated_at"])
            from hr_staff.services.audit_service import write_audit_event
            write_audit_event(tenant_id=self.tenant_id, action="IMPORT_COMMIT_FINISHED",
                actor_user_id=self.actor_user_id, business_type="HR03_IMPORT", business_id=str(locked.id),
                reason=f"committed={committed};failed={failed}", source="HR03")
            return self._result_for_job(locked)

    @staticmethod
    def _safe_commit_error(exc: Exception) -> str:
        """Return an actionable but non-secret error suitable for HR ledgers."""
        text = str(exc)
        if text == "IMPORT_DEPARTMENT_INVALID":
            return "部门不存在、已停用或不属于本校，请更正该行部门后重新校验"
        if text == "AUTHORITY_READBACK_MISSING":
            return "正式人员、主档、聘用或任职记录回读失败，本行已完整回滚，请联系管理员"
        if isinstance(exc, ImportRowValidationError):
            details = "；".join(f"{field}：{message}" for field, message in exc.errors.items())
            return f"提交前复核失败：{details}"[:500]
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
    def _authority_readback_count(job: HrImportJob) -> tuple[int, int]:
        """Compatibility entry point using the same strict row proof as XLSX."""
        from hr_staff.services.import_receipt_service import row_evidence
        rows = row_evidence(job)
        return (sum(x["verified"] for x in rows),
            sum("LEGACY_OR_INVALID_RECEIPT" in x["issues"] for x in rows))

    @staticmethod
    @transaction.atomic
    def _result_for_job(job: HrImportJob) -> dict:
        from hr_staff.services.import_receipt_service import inspect_locked_job, ImportReceiptLimit
        job = HrImportJob.objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        blocked = None
        try:
            proof = inspect_locked_job(job, include_issues=False)
            committed, failed, remaining = proof["committed"], proof["failed"], proof["pending"]
            readback, legacy_unverified = proof["verified"], proof["legacyUnverifiedRows"]
            readback_complete = proof["verificationStatus"] == "VERIFIED"
            accounting_issues = proof["accountingIssues"]
        except ImportReceiptLimit as exc:
            # Keep a corrupted/oversized historical job readable, but never
            # present a fabricated zero count as a completed authority check.
            committed = job.rows.filter(commit_status="COMMITTED").count()
            failed = job.rows.filter(is_valid=False).exclude(commit_status="COMMITTED").count()
            remaining = job.rows.count() - committed - failed
            readback = legacy_unverified = None
            readback_complete = False
            accounting_issues = []
            blocked = str(exc)
        resume_allowed = (
            job.status == ImportJobStatus.COMMITTING
            and isinstance(job.checkpoint, dict)
            and ImportService._commit_lease_is_stale(
                job, job.checkpoint, timezone.now()
            )
        )
        return {
            "jobId": str(job.id), "status": job.status, "resumeAllowed": resume_allowed,
            "remainingRows": remaining, "committed": committed, "failed": failed,
            "total": job.total_rows, "readbackCount": readback,
            "readbackComplete": readback_complete,
            "readbackScope": "PERSON_STAFF_EMPLOYMENT_ASSIGNMENT",
            "verificationScope": "PERSON_STAFF_EMPLOYMENT_PRIMARY_ASSIGNMENT_AND_ROW_AUDIT",
            "readbackBlocked": blocked, "accountingIssues": accounting_issues,
            "legacyUnverifiedRows": legacy_unverified,
        }


class StaffMasterRowApplier:
    """真实 row_applier：一行 = Person + StaffMaster + Relationship + Assignment 原子写。"""

    produces_staff_master = True

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def __call__(self, row_data: dict, checkpoint: dict):
        from hr_staff.constants import AssignmentType
        from hr_staff.models import (
            HrEmploymentRelationship,
            HrPerson,
            HrStaffAssignment,
            HrStaffMaster,
        )
        from hr_staff.services.assignment_service import AssignmentService
        from hr_staff.services.employment_service import EmploymentService
        from hr_staff.services.person_identity_service import PersonIdentityService
        from hr_staff.services.staff_master_service import StaffMasterService

        # Never trust preview state. Historical staging rows and recovery/retry
        # paths must pass the same canonical rules immediately before authority.
        row_data = validate_staff_import_row_for_commit(self.tenant_id, row_data)
        legal_name = row_data["legal_name"]
        effective_from = parse_import_date(
            row_data.get("effective_from"), field="effective_from", required=True
        )
        birth_date = parse_import_date(
            row_data.get("birth_date"), field="birth_date", required=False
        )
        legacy_dept = int(row_data["legacy_department_id"])
        hr02_organization_id = row_data.get("_hr02_organization_id")

        job_id = str(row_data.get("_import_job_id") or "direct")
        row_no = row_data.get("_import_row_no")
        if row_no is None:
            row_no = int(checkpoint.get("last_committed_row", 0) or 0) + 1
        source_business_id = f"import:{job_id}:row:{row_no}"

        person = PersonIdentityService().create_person_with_identity(
            tenant_id=self.tenant_id,
            legal_name=legal_name,
            gender_code=row_data.get("gender_code") or None,
            birth_date=birth_date,
            document_number=row_data.get("document_number") or None,
        )
        staff = StaffMasterService().create_staff(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no=row_data.get("staff_no") or None,
            staff_category_code=row_data["staff_category_code"],
            source="MIGRATED",
        )
        rel = EmploymentService(
            self.tenant_id, audit_actor_user_id=self.actor_user_id
        ).start_relationship(
            staff_id=staff,
            relationship_type=row_data["relationship_type"],
            effective_from=effective_from,
            source_business_type="MIGRATION_VERIFIED",
            source_business_id=source_business_id,
        )
        # First-use bulk import establishes a verified department assignment only.
        # Do not guess/invent an HR02 position from a legacy title. A formal position
        # is attached only when a verified mapping or a later appointment supplies it.
        assignment = AssignmentService(
            self.tenant_id, audit_actor_user_id=self.actor_user_id
        ).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=effective_from,
            organization_id=hr02_organization_id,
            legacy_department_id=legacy_dept,
            source_business_type="MIGRATION_VERIFIED",
            source_business_id=source_business_id,
        )

        # Read the authority records back from the database before the import row
        # can be marked COMMITTED.  A missing layer raises inside this savepoint,
        # which rolls Person/Staff/Employment/Assignment back together.
        readback_ok = (
            HrPerson.objects.filter(tenant_id=self.tenant_id, pk=person.pk).exists()
            and HrStaffMaster.objects.filter(
                tenant_id=self.tenant_id, pk=staff.pk, person_id=person
            ).exists()
            and HrEmploymentRelationship.objects.filter(
                tenant_id=self.tenant_id,
                pk=rel.pk,
                staff_id=staff,
                source_business_type="MIGRATION_VERIFIED",
                source_business_id=source_business_id,
            ).exists()
            and HrStaffAssignment.objects.filter(
                tenant_id=self.tenant_id,
                pk=assignment.pk,
                employment_relationship_id=rel,
                legacy_department_id=legacy_dept,
                organization_id_id=hr02_organization_id,
                source_business_type="MIGRATION_VERIFIED",
                source_business_id=source_business_id,
            ).exists()
        )
        if not readback_ok:
            raise ValueError("AUTHORITY_READBACK_MISSING")
        return staff

    @staticmethod
    def _parse_date(value):
        """Compatibility helper; no required-date fallback is allowed."""
        return parse_import_date(value, field="date", required=False)

