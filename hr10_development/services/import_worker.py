"""
hr10_development/services/import_worker.py

异步导入 Worker（S10）。

Excel 导入管线：parse → validation → error workbook → preview → confirm → execute。
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class LegacyImportSourceError(RuntimeError):
    """旧数据源不可读取时显式失败，禁止静默把 0 行当成功。"""


def run_import_job(job_id: int):
    """
    执行异步导入任务。

    状态流：PENDING → PARSE → VALIDATION → PREVIEW → CONFIRMING → EXECUTING → SUCCESS/FAILED
    """
    from hr10_development.legacy.import_job import HrDevelopmentImportJob

    try:
        job = HrDevelopmentImportJob.objects.get(id=job_id)
    except HrDevelopmentImportJob.DoesNotExist:
        logger.error("Import job %s not found", job_id)
        return

    job.status = "PARSE"
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        if "LEGACY_EMPLOYEE" in job.job_type:
            _parse_legacy_employee(job)
        elif "EXCEL" in job.job_type:
            _parse_excel(job)
        else:
            job.status = "FAILED"
            job.result_summary_json = {"error": f"Unknown job_type: {job.job_type}"}
            job.completed_at = timezone.now()
            job.save(
                update_fields=[
                    "status",
                    "result_summary_json",
                    "completed_at",
                    "updated_at",
                ]
            )
            return

        job.status = "SUCCESS"
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "completed_at", "updated_at"])

    except Exception as exc:
        job.status = "FAILED"
        job.result_summary_json = {"error": str(exc)[:2000]}
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "result_summary_json", "completed_at", "updated_at"])
        logger.exception("Import job %s failed", job_id)


def _parse_legacy_employee(job):
    """解析旧 Employee 数据；只进入 staging，不直接升级为正式发展事实。"""
    from hr10_development.legacy.staging import HrDevelopmentStagingRow

    try:
        from employee.models import Employee
    except ImportError as exc:
        raise LegacyImportSourceError("legacy employee model unavailable") from exc

    # Horilla Employee 没有 tenant_id；租户归属来自 EmployeeWorkInformation.company_id。
    # 必须显式 tenant scope，禁止依赖 request thread-local manager。
    employees = Employee.objects.filter(
        employee_work_info__company_id_id=job.tenant_id,
        is_active=True,
    ).order_by("id")[:5000]

    created = 0
    for emp in employees:
        qualification = (getattr(emp, "qualification", "") or "").strip()
        if not qualification:
            continue

        # 同一 job + legacy object + field 幂等；worker 重试不能重复堆 staging 行。
        _, was_created = HrDevelopmentStagingRow.objects.get_or_create(
            tenant_id=job.tenant_id,
            import_job_id=job.id,
            source_system="LEGACY_EMPLOYEE",
            source_table="Employee",
            source_field="qualification",
            source_object_id=str(emp.id),
            defaults={
                "raw_text": qualification,
                "migration_trust_level": "UNKNOWN",
                "verification_status": "PENDING",
                "target_model": "",
            },
        )
        if was_created:
            created += 1

    job.processed_rows = created
    job.result_summary_json = {
        "stagedRows": created,
        "message": "Legacy Employee data staged for review",
        "source": "employee.Employee.qualification",
        "trustLevel": "UNKNOWN",
        "authority": False,
    }
    job.save(update_fields=["processed_rows", "result_summary_json", "updated_at"])


def _parse_excel(job):
    """解析 Excel 文件。"""
    # S10: Excel 解析由 celery/cron job 驱动
    # 生产阶段：读取 file_hash → open workbook → row validation → create staging rows
    job.processed_rows = 0
    job.result_summary_json = {
        "message": "Excel parsing requires file storage integration (S10 placeholder)"
    }
    job.save(update_fields=["processed_rows", "result_summary_json", "updated_at"])
