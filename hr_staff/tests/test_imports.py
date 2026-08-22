"""S12b · ImportService staging 测试：解析/校验/精确失败行/分批 commit checkpoint。"""

from django.test import TestCase

from hr_staff.constants import ImportJobStatus
from hr_staff.models import HrImportIssue, HrImportRow
from hr_staff.services.import_service import ImportService
from hr_staff.services.staff_master_service import StaffNoConflict
from hr_staff.tests.factories import make_person

TENANT = 1


class ImportServiceTests(TestCase):
    def setUp(self):
        self.svc = ImportService(TENANT, actor_user_id=1)

    def test_parse_and_validate_rows(self):
        job = self.svc.create_job(template_key="staff_master")
        self.svc.parse_rows(
            job,
            [
                {"staff_no": "T100001", "legal_name": "张三"},
                {"staff_no": "", "legal_name": ""},  # 缺必填
            ],
        )
        self.assertEqual(job.total_rows, 2)
        self.svc.validate_rows(job, row_validator=lambda r: {"staff_no": "必填"} if not r.get("staff_no") else {})
        job.refresh_from_db()
        self.assertEqual(job.valid_rows, 1)
        self.assertEqual(job.failed_rows, 1)
        self.assertEqual(job.status, ImportJobStatus.READY_TO_COMMIT)
        self.assertEqual(HrImportIssue.objects.filter(job_id=job).count(), 1)

    def test_commit_with_precise_failed_rows(self):
        """commit：成功行写入、失败行精确标记，无半成功。"""
        job = self.svc.create_job(template_key="staff_master")
        self.svc.parse_rows(
            job,
            [
                {"staff_no": "T100001", "legal_name": "张三"},
                {"staff_no": "T100002", "legal_name": "李四"},
            ],
        )
        self.svc.validate_rows(job, row_validator=lambda r: {})

        created = {}

        def apply(row_data, checkpoint):
            if row_data["staff_no"] == "T100002":
                raise StaffNoConflict("模拟冲突")
            person = make_person(TENANT, row_data["legal_name"])
            created[row_data["staff_no"]] = person

        result = self.svc.commit(job, apply)
        self.assertEqual(result["committed"], 1)
        self.assertEqual(result["failed"], 1)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.PARTIAL_FAILED)
        # 失败行精确标记
        failed_row = HrImportRow.objects.get(job_id=job, row_no=3)
        self.assertEqual(failed_row.commit_status, "FAILED")
        self.assertEqual(HrImportIssue.objects.filter(job_id=job, error_code="COMMIT_FAILED").count(), 1)

    def test_checkpoint_resume_skips_committed(self):
        job = self.svc.create_job(template_key="staff_master")
        self.svc.parse_rows(
            job,
            [{"staff_no": f"T20{i}", "legal_name": f"员工{i}"} for i in range(3)],
        )
        self.svc.validate_rows(job, row_validator=lambda r: {})
        # Durable per-row commit state is the recovery authority. The checkpoint
        # is progress metadata only; rows 2/3 must already be COMMITTED for a
        # resumed process to skip them safely after a lost heartbeat/process.
        job.rows.filter(row_no__in=[2, 3]).update(commit_status="COMMITTED")
        job.checkpoint = {"last_committed_row": 3}
        job.save(update_fields=["checkpoint"])
        applied = []

        def apply(row_data, checkpoint):
            applied.append(row_data["staff_no"])

        self.svc.commit(job, apply)
        # 只处理第 3 数据行（row_no=4）
        self.assertEqual(applied, ["T202"])
