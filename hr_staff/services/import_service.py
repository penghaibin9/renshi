"""
hr_staff/services/import_service.py —— 导入 staging 服务（总册 §24）。

流程：上传 → 解析到 staging → 格式/字典/tenant/去重校验 → 预览 → 后台异步 commit。
V1 实现：解析 + 校验 + 精确失败行；commit 分批事务 + checkpoint，同人员多表原子。
"""

from __future__ import annotations

import json
from typing import Optional

from django.db import transaction

from hr_staff.constants import ImportJobStatus
from hr_staff.models import HrImportIssue, HrImportJob, HrImportRow


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
            original_filename=original_filename,
        )

    def job_for_id(self, job_id) -> Optional[HrImportJob]:
        return HrImportJob.objects.filter(tenant_id=self.tenant_id, id=job_id).first()

    def parse_rows(self, job: HrImportJob, rows: list[dict]):
        """把 Excel 行解析进 staging（不写 authority）。"""
        job.status = ImportJobStatus.VALIDATING
        job.total_rows = len(rows)
        job.save(update_fields=["status", "total_rows"])
        for idx, row in enumerate(rows, start=2):  # Excel 第 1 行为表头
            HrImportRow.objects.create(
                tenant_id=self.tenant_id,
                job_id=job,
                row_no=idx,
                data_json=row,
            )
        return job

    def validate_rows(self, job: HrImportJob, row_validator) -> HrImportJob:
        """逐行校验；不通过标记 is_valid=False + 写 HrImportIssue（精确失败行）。"""
        for row in job.rows.all():
            errors = row_validator(row.data_json)
            if errors:
                row.is_valid = False
                row.error_summary = "; ".join(errors.values())[:500]
                row.save(update_fields=["is_valid", "error_summary"])
                for field, message in errors.items():
                    HrImportIssue.objects.create(
                        tenant_id=self.tenant_id,
                        job_id=job,
                        row_id=row,
                        row_no=row.row_no,
                        field_code=field,
                        error_code="VALIDATION_ERROR",
                        message=message,
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
    def commit(self, job: HrImportJob, row_applier, batch_size: int = 100) -> dict:
        """
        row_applier(row_data, checkpoint) → dict 或抛错（多表写在内部 atomic）。
        P2-3：外层不包大事务；每行独立 atomic + checkpoint 落库，进程崩溃可精确续跑。
        """
        job.status = ImportJobStatus.COMMITTING
        job.save(update_fields=["status"])

        committed = 0
        failed = 0
        checkpoint = dict(job.checkpoint or {})

        valid_rows = list(job.rows.filter(is_valid=True).order_by("row_no"))
        for row in valid_rows:
            if checkpoint.get("last_committed_row") and row.row_no <= checkpoint["last_committed_row"]:
                continue  # 从 checkpoint 续跑
            try:
                with transaction.atomic():
                    row_applier(row.data_json, checkpoint)
                with transaction.atomic():
                    row.commit_status = "COMMITTED"
                    row.save(update_fields=["commit_status"])
                committed += 1
                checkpoint["last_committed_row"] = row.row_no
            except Exception as exc:
                with transaction.atomic():
                    row.commit_status = "FAILED"
                    row.is_valid = False
                    row.error_summary = f"{exc.__class__.__name__}: {exc}"[:500]
                    row.save(update_fields=["commit_status", "is_valid", "error_summary"])
                    HrImportIssue.objects.create(
                        tenant_id=self.tenant_id,
                        job_id=job,
                        row_id=row,
                        row_no=row.row_no,
                        error_code="COMMIT_FAILED",
                        message=str(exc)[:500],
                    )
                failed += 1
            # checkpoint 每 50 行落库一次（中断恢复点）
            if committed % 50 == 0:
                job.checkpoint = checkpoint
                job.save(update_fields=["checkpoint"])

        job.checkpoint = checkpoint
        job.committed_by = self.actor_user_id
        job.status = (
            ImportJobStatus.COMPLETED
            if failed == 0
            else ImportJobStatus.PARTIAL_FAILED
        )
        job.save(update_fields=["checkpoint", "committed_by", "status"])
        return {"committed": committed, "failed": failed, "total": job.total_rows}


class StaffMasterRowApplier:
    """真实 row_applier（P1-i）：一行 = Person + StaffMaster + Relationship + Assignment 原子写。

    数据列（template_key=staff_master）：
    staff_no / legal_name / gender_code / birth_date / document_number /
    staff_category_code / relationship_type / effective_from / legacy_department_id
    """

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    @transaction.atomic
    def __call__(self, row_data: dict, checkpoint: dict):
        from datetime import date

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
        effective_from = self._parse_date(row_data.get("effective_from")) or date.today()
        source_business_id = (
            f"import-row-{row_data.get('row_no', checkpoint.get('last_committed_row', 0))}"
        )
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
        from datetime import datetime

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(str(value).strip(), fmt).date()
            except ValueError:
                continue
        raise ValueError(f"无效日期: {value}")
