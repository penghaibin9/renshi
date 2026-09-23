#!/usr/bin/env python3
"""Static release gate for Round10 HR18 procurement-grade sync operations.

The referenced procurement checklist is used only as an acceptance-quality
reference. This gate verifies source/schema/UI/test contracts without Django;
it does not replace migration, MySQL, provider, browser or load testing.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[dict] = []


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})


def has_all(source: str, *needles: str) -> bool:
    return all(needle in source for needle in needles)


paths = {
    "models": "backend/hr_data/models.py",
    "service": "backend/hr_data/services/exchange_service.py",
    "api": "backend/hr_data/exchange_api.py",
    "urls": "backend/hr_data/api_urls.py",
    "migration": "backend/hr_data/migrations/0019_exchange_manual_retry_provenance.py",
    "ui": "frontend/static/hr/js/pages/hr18-actions.js",
    "service_tests": "backend/hr_data/tests/test_exchange_service.py",
    "api_tests": "backend/hr_data/tests/test_exchange_api.py",
    "pure_tests": "tests/round10/test_procurement_sync_contract.py",
    "perf_probe": "scripts/run_procurement_performance_probe.py",
}
src = {key: text(rel) for key, rel in paths.items()}

for key in ("models", "service", "api", "urls", "migration", "service_tests", "api_tests", "pure_tests", "perf_probe"):
    try:
        ast.parse(src[key], filename=paths[key])
        record(f"ast:{key}", True, paths[key])
    except SyntaxError as exc:
        record(f"ast:{key}", False, f"{paths[key]}: {exc}")

model_start = src["models"].index("class ExchangeJob(")
model_end = src["models"].index("class ExchangeAttempt(", model_start)
job_model = src["models"][model_start:model_end]
submission_start = src["models"].index("class SubmissionDispatchJob(")
submission_end = src["models"].index("class SubmissionDispatchAttempt(", submission_start)
submission_model = src["models"][submission_start:submission_end]

record(
    "retry_provenance_lives_on_exchange_job",
    has_all(
        job_model,
        "retry_of_job = models.ForeignKey",
        "manual_retry_reason = models.TextField",
        "manual_retry_by = models.BigIntegerField",
        'name="idx_hr18_exchange_retry_of"',
    )
    and "manual_retry_reason = models.TextField" not in submission_model,
    "manual retry provenance belongs to ExchangeJob, not the separate formal-submission worker",
)
record(
    "migration_matches_model_state",
    src["migration"].count("migrations.AddField") == 3
    and src["migration"].count("migrations.AddIndex") == 1
    and 'name="idx_hr18_exchange_retry_of"' in src["migration"]
    and "RunPython" not in src["migration"],
    "0019 is schema-only and matches source model/index state",
)

service_start = src["service"].index("def requeue_dead_letter")
service_end = src["service"].index("def _load_provider", service_start)
retry_service = src["service"][service_start:service_end]
record(
    "manual_retry_is_atomic_and_terminal_only",
    "@transaction.atomic" in src["service"][max(0, service_start - 80):service_start]
    and has_all(
        retry_service,
        "select_for_update()",
        "source.status != ExchangeJob.Status.DEAD_LETTER",
        "ExchangeDeadLetter.objects.select_for_update()",
    ),
    "source failure and dead-letter row are locked inside one transaction",
)
record(
    "manual_retry_preserves_original_evidence",
    has_all(
        retry_service,
        "retry_of_job_id=source.id",
        "status=ExchangeJob.Status.QUEUED",
        "dead_letter.resolved_at = timezone.now()",
    )
    and retry_service.index("ExchangeJob.objects.create")
    < retry_service.index("dead_letter.resolved_at = timezone.now()")
    and "source.status =" not in retry_service
    and "source.delete" not in retry_service,
    "new successor is appended before resolution; source job/attempt history is not rewritten",
)
record(
    "manual_retry_idempotency_is_exact",
    has_all(
        retry_service,
        "existing.retry_of_job_id == source.id",
        "existing.job_no == new_job_no",
        "existing.manual_retry_reason == reason",
        "existing.max_attempts == attempts",
        "EXCHANGE_IDEMPOTENCY_CONFLICT",
    ),
    "reusing an idempotency key with changed retry command parameters fails closed",
)
record(
    "manual_retry_is_tenant_scoped",
    retry_service.count("tenant_id=self.tenant_id") >= 4,
    "source, dead-letter, idempotency and job-number lookups are tenant-scoped",
)

record(
    "workbench_exposes_mapping_and_health",
    has_all(
        src["api"],
        '"mapping": row.mapping_json',
        '"syncHealth"',
        '"pendingCount"',
        '"transmittedCount"',
        '"reconciledCount"',
        '"failureCount"',
        '"unresolvedFailureCount"',
        '"latestJobStatus"',
        '"latestErrorCode"',
        '"latestUnresolvedFailureReason"',
        '"latestUnresolvedFailureAt"',
    ),
    "current field mapping plus current/historical sync health are observable",
)
record(
    "success_time_has_explicit_semantics",
    has_all(
        src["api"],
        "last_transmitted_at=Max(",
        "last_reconciled_at=Max(",
        '"successSemantics": "RECONCILED" if row.expected_receipt else "TRANSMITTED"',
    ),
    "targets requiring receipts do not call transport-only success an end-to-end success",
)
record(
    "unresolved_failures_are_distinct_from_history",
    has_all(
        src["api"],
        "unresolved_failure_count=Count(",
        "exchange_jobs__dead_letter__resolved_at__isnull=True",
        "latest_unresolved_failure = ExchangeDeadLetter.objects.filter(",
        'latest_unresolved_failure.values("reason_code")',
    )
    and has_all(src["ui"], "待人工处理", "历史最终失败"),
    "manual work queue does not confuse preserved historical failures with unresolved failures",
)
record(
    "single_and_batch_retry_api",
    has_all(src["api"], "def retry_job(request, job_id):", "def retry_batch(request):", ".requeue_dead_letter(")
    and has_all(src["urls"], '"exchange/jobs/retry-batch/"', '"exchange/jobs/<uuid:job_id>/retry/"'),
    "single and batch manual requeue endpoints are wired",
)
record(
    "batch_retry_bounded_and_partial",
    has_all(
        src["api"],
        "1 <= len(items) <= 100",
        '"successCount": success_count',
        '"failureCount": len(items) - success_count',
        '"partial": success_count != len(items)',
        '"ok": False',
    ),
    "batch operations cannot be unbounded and do not fake all-success",
)
record(
    "exchange_permission_still_fail_closed",
    has_all(src["api"], 'EXCHANGE_PERMISSION = "hr.data.exchange"', "resolve_request_tenant(request, required_permission=EXCHANGE_PERMISSION)"),
    "new operational endpoints reuse the existing tenant + exchange permission gate",
)
record(
    "operator_ui_has_health_and_retry_actions",
    has_all(
        src["ui"],
        "hr18-exchange-health",
        "successSemantics",
        "data-manual-retry",
        "data-retry-failed-batch",
        "/exchange/jobs/retry-batch/",
        "失败任务已保留",
    ),
    "operators can see health and intentionally retry terminal failures without deleting evidence",
)
record(
    "procurement_performance_probe_is_executable_and_safe_by_default",
    has_all(
        src["perf_probe"],
        'default=100',
        'default=3000.0',
        'default=5000.0',
        '--allow-load',
        'NoRedirect',
        'method="GET"',
        '"headerNames"',
        'safe_url(target.url)',
    ),
    "3s/5s and 100-concurrency reference targets are an executable read-only QA gate that refuses accidental load by default",
)

record(
    "dynamic_regressions_are_present",
    all(
        name in (src["service_tests"] + src["api_tests"])
        for name in (
            "test_manual_retry_appends_successor_without_rewriting_terminal_failure",
            "test_manual_retry_is_tenant_scoped_and_dead_letter_only",
            "test_manual_retry_endpoint_returns_successor_provenance",
            "test_manual_retry_batch_reports_partial_failure_per_item",
        )
    ),
    "Django/MySQL runtime cases are checked into source even when this sandbox cannot execute them",
)

passed = sum(1 for item in CHECKS if item["ok"])
result = {
    "gate": "HR18_PROCUREMENT_SYNC_CONTRACT_STATIC",
    "status": "PASS" if passed == len(CHECKS) else "FAIL",
    "passed": passed,
    "total": len(CHECKS),
    "checks": CHECKS,
    "scopeNote": (
        "Static/AST acceptance gate only. Django/MySQL migrations, external provider behavior, "
        "browser flows and the procurement performance targets require a QA runtime."
    ),
}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if result["status"] == "PASS" else 1)
