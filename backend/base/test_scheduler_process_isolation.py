import inspect
from pathlib import Path

from django.test import SimpleTestCase

from attendance.apps import AttendanceConfig
from base.management.commands.run_legacy_scheduler import build_scheduler


class SchedulerProcessIsolationTests(SimpleTestCase):
    def test_web_app_imports_do_not_start_background_schedulers(self):
        repository_backend = Path(__file__).resolve().parents[1]
        package_initializers = (
            repository_backend / "base" / "__init__.py",
            repository_backend / "asset" / "__init__.py",
            repository_backend / "leave" / "__init__.py",
            repository_backend / "pms" / "__init__.py",
        )
        for path in package_initializers:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import scheduler", source, path)
            self.assertNotIn("scheduler.start", source, path)

        payroll_scheduler = (
            repository_backend / "payroll" / "scheduler.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("BackgroundScheduler", payroll_scheduler)
        self.assertNotIn("scheduler.start", payroll_scheduler)

        for path in (
            repository_backend / "biometric" / "views.py",
            repository_backend / "biometric" / "cbv" / "biometric.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("BackgroundScheduler", source, path)
            self.assertNotIn("scheduler.start", source, path)

        ready_source = inspect.getsource(AttendanceConfig.ready)
        self.assertNotIn("from attendance import scheduler", ready_source)

    def test_dedicated_scheduler_owns_every_scheduled_job_once(self):
        scheduler = build_scheduler()
        job_ids = [job.id for job in scheduler.get_jobs()]
        self.assertEqual(len(job_ids), 27)
        self.assertEqual(len(job_ids), len(set(job_ids)))
        self.assertIn("attendance.auto_punch_out", job_ids)
        self.assertIn("asset.mark_expired_assets", job_ids)
        self.assertIn("leave.reset", job_ids)
        self.assertIn("pms.cyclic_feedback", job_ids)
        self.assertIn("recruitment.close", job_ids)
        self.assertIn("runtime.legacy_scheduler_heartbeat", job_ids)
        self.assertIn("biometric.reconcile_schedules", job_ids)
        self.assertIn("hr07.canonical_contract_expiry", job_ids)
        self.assertIn("hr04.candidate_retention", job_ids)
        self.assertIn("hr16.canonical_retirement_prechecks", job_ids)
        self.assertIn("hr08.iam_provisioning_dispatch", job_ids)
        self.assertIn("hr08.academic_provisioning_dispatch", job_ids)
        self.assertIn("hr08.import_job_runner", job_ids)
        self.assertIn("hr08.expire_engagements", job_ids)
