import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class ProcurementReferenceSyncContracts(unittest.TestCase):
    def test_exchange_model_keeps_retry_provenance_without_rewriting_source_job(self):
        source = text("backend/hr_data/models.py")
        start = source.index("class ExchangeJob(")
        end = source.index("class ExchangeAttempt(", start)
        block = source[start:end]
        submission_start = source.index("class SubmissionDispatchJob(")
        submission_end = source.index("class SubmissionDispatchAttempt(", submission_start)
        submission_block = source[submission_start:submission_end]
        for token in (
            "retry_of_job = models.ForeignKey",
            "manual_retry_reason = models.TextField",
            "manual_retry_by = models.BigIntegerField",
            '"retry_of_job_id"',
            '"manual_retry_reason"',
            '"manual_retry_by"',
            'name="idx_hr18_exchange_retry_of"',
        ):
            self.assertIn(token, block)
        self.assertNotIn("manual_retry_reason = models.TextField", submission_block)
        self.assertNotIn("manual_retry_by = models.BigIntegerField", submission_block)

    def test_manual_retry_service_is_dead_letter_only_and_preserves_original_evidence(self):
        source = text("backend/hr_data/services/exchange_service.py")
        start = source.index("def requeue_dead_letter")
        end = source.index("def _load_provider", start)
        block = source[start:end]
        self.assertIn("source.status != ExchangeJob.Status.DEAD_LETTER", block)
        self.assertIn("manual retry reason is required", block)
        self.assertIn("retry_of_job_id=source.id", block)
        self.assertIn("existing.job_no == new_job_no", block)
        self.assertIn("existing.manual_retry_reason == reason", block)
        self.assertIn("existing.max_attempts == attempts", block)
        self.assertIn("status=ExchangeJob.Status.QUEUED", block)
        self.assertIn("dead_letter.resolved_at = timezone.now()", block)
        self.assertLess(
            block.index("ExchangeJob.objects.create"),
            block.index("dead_letter.resolved_at = timezone.now()"),
        )
        self.assertNotIn("source.status =", block)
        self.assertNotIn("source.delete", block)

    def test_exchange_workbench_exposes_current_mapping_and_sync_health(self):
        source = text("backend/hr_data/exchange_api.py")
        for token in (
            '"mapping": row.mapping_json',
            '"syncHealth"',
            '"pendingCount"',
            '"transmittedCount"',
            '"reconciledCount"',
            '"failureCount"',
            '"unresolvedFailureCount"',
            '"lastSuccessAt"',
            '"successSemantics"',
            '"latestErrorCode"',
            '"latestUnresolvedFailureReason"',
            '"latestUnresolvedFailureAt"',
        ):
            self.assertIn(token, source)
        self.assertIn("Subquery(latest_target_job.values", source)
        self.assertIn('last_transmitted_at=Max(', source)
        self.assertIn('last_reconciled_at=Max(', source)
        self.assertIn('latest_unresolved_failure = ExchangeDeadLetter.objects.filter(', source)
        self.assertIn('latest_unresolved_failure.values("reason_code")', source)

    def test_single_and_batch_manual_retry_api_are_tenant_scoped_service_calls(self):
        api = text("backend/hr_data/exchange_api.py")
        urls = text("backend/hr_data/api_urls.py")
        self.assertIn("def retry_job(request, job_id):", api)
        self.assertIn("def retry_batch(request):", api)
        self.assertIn("tenant_id, payload, error = _prepare(request)", api)
        self.assertIn(".requeue_dead_letter(", api)
        self.assertIn('"exchange/jobs/retry-batch/"', urls)
        self.assertIn('"exchange/jobs/<uuid:job_id>/retry/"', urls)

    def test_batch_retry_is_bounded_and_returns_partial_results_instead_of_fake_success(self):
        source = text("backend/hr_data/exchange_api.py")
        start = source.index("def retry_batch")
        end = source.index("def record_receipt", start)
        block = source[start:end]
        self.assertIn("1 <= len(items) <= 100", block)
        self.assertIn('"failureCount": len(items) - success_count', block)
        self.assertIn('"partial": success_count != len(items)', block)
        self.assertIn('"ok": False', block)
        self.assertIn('"code": exc.code', block)

    def test_exchange_ui_shows_health_and_single_batch_retry_actions(self):
        source = text("frontend/static/hr/js/pages/hr18-actions.js")
        for token in (
            "hr18-exchange-health",
            "successSemantics",
            "待人工处理",
            "历史最终失败",
            "data-manual-retry",
            "data-retry-failed-batch",
            "/exchange/jobs/retry-batch/",
            "/retry/`,",
            "失败任务已保留",
        ):
            self.assertIn(token, source)

    def test_retry_migration_only_adds_provenance_schema(self):
        source = text("backend/hr_data/migrations/0019_exchange_manual_retry_provenance.py")
        self.assertIn('("hr_data", "0018_operational_snapshot_seals")', source)
        self.assertEqual(source.count("migrations.AddField"), 3)
        self.assertEqual(source.count("migrations.AddIndex"), 1)
        self.assertNotIn("RunPython", source)

    def test_round10_static_gate_is_green(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_hr18_procurement_sync_contract.py")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["passed"], payload["total"])

    def test_performance_probe_refuses_accidental_load_without_explicit_flag(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/run_procurement_performance_probe.py"),
                "--normal-url",
                "http://127.0.0.1/",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--allow-load", completed.stderr)

    def test_changed_python_files_parse(self):
        for rel in (
            "backend/hr_data/models.py",
            "backend/hr_data/services/exchange_service.py",
            "backend/hr_data/exchange_api.py",
            "backend/hr_data/api_urls.py",
            "backend/hr_data/migrations/0019_exchange_manual_retry_provenance.py",
        ):
            ast.parse(text(rel))


if __name__ == "__main__":
    unittest.main()
