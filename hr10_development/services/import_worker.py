"""
hr10_development/services/import_worker.py

异步导入 Worker（S10）。

Excel 导入管线：parse → validation → error workbook → preview → confirm → execute。
"""

import logging

logger = logging.getLogger(__name__)


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
    job.started_at = __import__("django").utils.timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        if "LEGACY_EMPLOYEE" in job.job_type:
            _parse_legacy_employee(job)
        elif "EXCEL" in job.job_type:
            _parse_excel(job)
        else:
            job.status = "FAILED"
            job.result_summary_json = {"error": f"Unknown job_type: {job.job_type}"}
            job.save(update_fields=["status", "result_summary_json", "updated_at"])
            return

        job.status = "SUCCESS"
        job.completed_at = __import__("django").utils.timezone.now()
        job.save(update_fields=["status", "completed_at", "updated_at"])

    except Exception as exc:
        job.status = "FAILED"
        job.result_summary_json = {"error": str(exc)[:2000]}
        job.completed_at = __import__("django").utils.timezone.now()
        job.save(update_fields=["status", "result_summary_json", "completed_at", "updated_at"])
        logger.exception("Import job %s failed", job_id)


def _parse_legacy_employee(job):
    """解析旧 Employee 数据。"""
    from hr10_development.legacy.staging import HrDevelopmentStagingRow

    # S10: 从旧 Employee 表读取 qualification/note 字段
    # 生产阶段对接真实 employee.models.Employee
    created = 0
    try:
        from employee.models import Employee
        employees = Employee.objects.filter(tenant_id=job.tenant_id, is_active=True)[:5000]
        for emp in employees:
            if emp.qualification:
                HrDevelopmentStagingRow.objects.create(
                    tenant_id=job.tenant_id,
                    source_system="LEGACY_EMPLOYEE",
                    source_table="Employee",
                    source_field="qualification",
                    source_object_id=str(emp.id),
                    raw_text=emp.qualification,
                    migration_trust_level="UNKNOWN",
                    import_job_id=job.id,
                    status="PENDING",
                )
                created += 1
    except Exception:
        logger.warning("Legacy Employee parse: employee model unavailable in S10 staging")

    job.processed_rows = created
    job.result_summary_json = {"stagedRows": created, "message": "Legacy Employee data staged for review"}
    job.save(update_fields=["processed_rows", "result_summary_json"])


def _parse_excel(job):
    """解析 Excel 文件。"""
    # S10: Excel 解析由 celery/cron job 驱动
    # 生产阶段：读取 file_hash → open workbook → row validation → create staging rows
    job.processed_rows = 0
    job.result_summary_json = {"message": "Excel parsing requires file storage integration (S10 placeholder)"}
    job.save(update_fields=["processed_rows", "result_summary_json"])
