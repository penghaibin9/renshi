#!/usr/bin/env python3
"""Static release gate for the HR10 Excel import execution contract.

Runs without Django so it can still verify the code package in restricted build
sandboxes. It intentionally checks source/AST contracts only; it does not replace
the Django/MySQL regression suite.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def has_all(haystack: str, needles: list[str]) -> bool:
    return all(needle in haystack for needle in needles)


files = {
    "job": "backend/hr10_development/legacy/import_job.py",
    "staging": "backend/hr10_development/legacy/staging.py",
    "worker": "backend/hr10_development/services/import_worker.py",
    "api": "backend/hr10_development/api/imports.py",
    "urls": "backend/hr10_development/api/urls.py",
    "migration": "backend/hr10_development/migrations/0025_import_claim_lease_and_execution.py",
    "tests": "backend/hr10_development/tests/test_excel_import_pipeline.py",
}
source = {key: text(path) for key, path in files.items()}

# Every modified Python file must parse independently of framework imports.
for key, rel in files.items():
    try:
        ast.parse(source[key], filename=rel)
        record(f"ast:{key}", True, rel)
    except SyntaxError as exc:
        record(f"ast:{key}", False, f"{rel}: {exc}")

record(
    "lease_fields",
    has_all(source["job"], ["claim_token = models.CharField", "lease_expires_at = models.DateTimeField", "heartbeat_at = models.DateTimeField"]),
    "claim token + expiry + heartbeat are persisted",
)
record(
    "lease_claim_parse",
    has_all(source["worker"], ["def _claim_parse_job", "select_for_update()", "_lease_is_active", "leaseTakeovers", "def _heartbeat"]),
    "duplicate parse delivery is lease-guarded and stale work can be reclaimed",
)
record(
    "lease_claim_execute",
    has_all(source["worker"], ["def _claim_execution_job", 'status = "CONFIRMING"', 'status = "EXECUTING"', "ImportJobBusy"]),
    "confirmation/execution also owns a lease",
)
record(
    "execution_atomic",
    has_all(source["worker"], ["def _execute_rows_atomic", "with transaction.atomic():", 'locked.status = "SUCCESS"', "HrDevelopmentAuditEvent.objects.bulk_create"]),
    "authority rows + success state + audit share one transaction",
)
record(
    "real_authority_targets",
    has_all(source["worker"], ["HrDevelopmentPlan", "HrLearningProgram", "HrEnterprisePracticeProject", "target.save(force_insert=True)"]),
    "all supported Excel job types build real HR10 authority rows",
)
record(
    "individual_plan_staff_key_canonicalized",
    has_all(
        source["worker"],
        [
            "staff_master_uuid",
            "staff_master_legacy_id",
            "HrStaffMaster.objects.filter",
            "AMBIGUOUS_LEGACY_MAPPING",
        ],
    )
    and "HR03_UUID_CONTRACT_MISMATCH" not in source["worker"],
    "individual-plan rows resolve tenant-scoped HR03 UUIDs in batch and retain legacy ids only as compatibility metadata",
)
record(
    "batch_execution_recheck",
    source["worker"].count("_batch_authority_validation_errors(") >= 3 and "AUTHORITY_CONFLICT_AT_EXECUTION" in source["worker"],
    "preview and pre-write conflict checks are batched",
)
record(
    "row_execution_receipt",
    has_all(source["staging"], ["execution_status = models.CharField", "executed_at = models.DateTimeField", "uniq_hr10_staging_import_row"])
    and has_all(source["worker"], ['row.execution_status = "SUCCESS"', "row.target_id = target.pk", "ImportRowExecuted"]),
    "each source row retains target id, execution status/time and audit",
)
record(
    "api_no_fake_success",
    'job.status = "SUCCESS"' not in source["api"] and "execute_import_job(" in source["api"],
    "confirm endpoint delegates to transactional execution instead of flipping status",
)
record(
    "tenant_scoped_execution",
    has_all(source["worker"], ["tenant_id=tenant_id", "tenant_id=job.tenant_id"]) and "IMPORT_NOT_FOUND" in source["worker"],
    "job/authority operations are tenant-scoped",
)
record(
    "row_results_endpoint",
    "def get_import_rows" in source["api"] and 'imports/<int:job_id>/rows' in source["urls"],
    "row-level execution results are observable through a paginated endpoint",
)
record(
    "migration_fail_closed_dedup",
    has_all(source["migration"], ["RunPython", "HR10_STAGING_DUPLICATE_TARGET_CONFLICT", "UniqueConstraint", "claim_token", "lease_expires_at"]),
    "schema upgrade de-duplicates safely and blocks conflicting historical target links",
)
required_tests = [
    "test_active_parse_lease_blocks_duplicate_worker_and_expired_lease_is_reclaimed",
    "test_individual_plan_import_resolves_hr03_uuid_and_executes",
    "test_individual_plan_legacy_id_is_accepted_only_through_tenant_mapping",
    "test_confirm_executes_authority_write_row_result_audit_and_replay_is_idempotent",
    "test_authority_conflict_after_preview_fails_closed_and_marks_row_failure",
    "test_execution_is_tenant_scoped",
    "test_active_execution_lease_rejects_duplicate_confirm",
]
record(
    "regression_tests_present",
    all(name in source["tests"] for name in required_tests),
    f"{len(required_tests)} targeted regression cases are present",
)

modified_hashes = {}
for rel in files.values():
    payload = (ROOT / rel).read_bytes()
    modified_hashes[rel] = hashlib.sha256(payload).hexdigest()

passed = sum(1 for check in CHECKS if check["ok"])
result = {
    "gate": "HR10_IMPORT_CONTRACT_STATIC",
    "passed": passed,
    "total": len(CHECKS),
    "status": "PASS" if passed == len(CHECKS) else "FAIL",
    "checks": CHECKS,
    "sha256": modified_hashes,
    "scopeNote": "Static/AST gate only; Django/MySQL runtime regression must run in an environment with project dependencies.",
}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if result["status"] == "PASS" else 1)
