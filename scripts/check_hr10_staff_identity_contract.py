#!/usr/bin/env python3
"""Static release gate for HR10 -> HR03 canonical staff identity.

No Django import is required.  The gate verifies source/schema/migration
contracts only; real Django/MySQL migrate + regression still belongs in QA.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = []


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def record(name, ok, detail=""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})


def all_in(source, *needles):
    return all(item in source for item in needles)


paths = {
    "hr03": "backend/hr_staff/models/staff.py",
    "identity": "backend/hr10_development/identity.py",
    "fact": "backend/hr10_development/models/development_fact.py",
    "enrollment_model": "backend/hr10_development/models/enrollment.py",
    "m26": "backend/hr10_development/migrations/0026_canonical_hr03_staff_uuid.py",
    "m27": "backend/hr10_development/migrations/0027_backfill_hr10_staff_uuid.py",
    "m28": "backend/hr10_development/migrations/0028_hr10_staff_identity_guards.py",
    "plan": "backend/hr10_development/services/plan_service.py",
    "requests": "backend/hr10_development/api/requests.py",
    "approval": "backend/hr10_development/services/approval_service.py",
    "enrollment": "backend/hr10_development/services/enrollment_service.py",
    "practice": "backend/hr10_development/api/practice.py",
    "output": "backend/hr10_development/api/practice_process.py",
    "records": "backend/hr10_development/api/development_records.py",
    "urls": "backend/hr10_development/api/urls.py",
    "ui_urls": "backend/hr10_development/urls.py",
    "workbench": "backend/hr10_development/api/workbench.py",
    "views": "backend/hr10_development/views.py",
    "time": "backend/hr10_development/providers/time_provider.py",
    "public": "backend/hr10_development/public.py",
    "import_worker": "backend/hr10_development/services/import_worker.py",
    "authority": "backend/hr10_development/services/development_fact_authority_service.py",
    "further": "backend/hr10_development/services/further_study_service.py",
}
src = {k: text(v) for k, v in paths.items()}

for key, rel in paths.items():
    try:
        ast.parse(src[key], filename=rel)
        record(f"ast:{key}", True, rel)
    except SyntaxError as exc:
        record(f"ast:{key}", False, f"{rel}: {exc}")

record(
    "hr03_uuid_authority",
    all_in(src["hr03"], "id = models.UUIDField", "legacy_employee_id = models.BigIntegerField"),
    "HR03 UUID remains authoritative while legacy Employee id is an adapter key",
)
record(
    "resolver_uuid_first_tenant_scoped",
    all_in(
        src["identity"],
        "parsed_uuid = _parse_uuid(raw)",
        "tenant_id=tenant_id, id=parsed_uuid",
        "tenant_id=tenant_id, legacy_employee_id=legacy_id",
        ").exclude(id=staff.id).exists()",
        "STAFF_IDENTITY_AMBIGUOUS",
    ),
    "canonical UUID resolves first; numeric compatibility is tenant-scoped and ambiguity fails closed",
)
record(
    "dual_read_query_contract",
    all_in(
        src["identity"],
        "staff_master_uuid__isnull",
        "staff_master_id\": identity.legacy_employee_id",
    ),
    "readers can see untouched historic legacy rows without weakening canonical writes",
)

model_files = [
    "backend/hr10_development/models/plan.py",
    "backend/hr10_development/models/training_request.py",
    "backend/hr10_development/models/enrollment.py",
    "backend/hr10_development/models/need.py",
    "backend/hr10_development/models/further_study.py",
    "backend/hr10_development/models/practice_models.py",
    "backend/hr10_development/models/practice_process.py",
    "backend/hr10_development/models/development_fact.py",
]
model_text = "\n".join(text(path) for path in model_files)
record(
    "canonical_columns_cover_all_staff_aggregates",
    model_text.count("staff_master_uuid = models.UUIDField") == 10,
    "10 HR10 staff-bearing models carry the canonical UUID column",
)
record(
    "enrollment_canonical_unique_guard",
    all_in(src["enrollment_model"], "uq_hr10_enroll_offering_staff_uuid", 'fields=["tenant_id", "offering_id", "staff_master_uuid"]'),
    "duplicate enrollment is constrained by tenant/offering/canonical staff",
)
record(
    "fact_uuid_index_state_matches_migration",
    all_in(src["fact"], 'name="hr_dev_fact_uuid_type_valid_idx"')
    and all_in(src["m28"], "FACT_UUID_INDEX = \"hr_dev_fact_uuid_type_valid_idx\""),
    "model state and retry-safe DB migration use the same canonical fact index name",
)
record(
    "schema_migration_is_ddl_only",
    src["m26"].count("migrations.AddField") == 10
    and "migrations.RunPython" not in src["m26"]
    and "0025_import_claim_lease_and_execution" in src["m26"],
    "0026 contains schema changes only so MySQL dirty data cannot strand a half-recorded data migration",
)
record(
    "backfill_preflights_before_writes",
    all_in(src["m27"], "_collect_required_mappings", "HR10_STAFF_UUID_BACKFILL_AMBIGUOUS", "HR10_STAFF_UUID_BACKFILL_MISSING")
    and src["m27"].index("required = _collect_required_mappings") < src["m27"].index("bulk_update"),
    "0027 validates all mutable legacy references before the first backfill write",
)
record(
    "sealed_facts_not_rewritten",
    '"HrDevelopmentFact"' not in src["m27"].split("_MUTABLE_MODEL_NAMES =", 1)[1].split(")", 1)[0]
    and "Sealed ``HrDevelopmentFact`` history is intentionally not rewritten" in src["m27"],
    "append-only V1 fact hashes remain intact",
)
record(
    "guard_migration_retry_safe",
    all_in(src["m28"], "get_constraints", "if ENROLLMENT_CONSTRAINT not in names", "if FACT_UUID_INDEX not in names", "SeparateDatabaseAndState"),
    "constraint/index database operations can be retried after an interrupted MySQL migration",
)
record(
    "required_staff_rows_keep_nonempty_identity_guard",
    src["m28"].count("constraint=_identity_check(") >= 7
    and all(
        name in (model_text + src["m28"])
        for name in (
            "ck_hr10_request_staff_identity",
            "ck_hr10_enroll_staff_identity",
            "ck_hr10_study_staff_identity",
            "ck_hr10_practice_staff_identity",
            "ck_hr10_output_staff_identity",
            "ck_hr10_fact_staff_identity",
            "ck_hr10_metric_staff_identity",
        )
    ),
    "making legacy bigint nullable does not permit staff-required rows with both identity keys empty",
)
record(
    "fact_parent_trigger_prefers_uuid",
    all_in(src["m28"], "parent.staff_master_uuid = NEW.staff_master_uuid", "parent.staff_master_uuid IS NULL OR NEW.staff_master_uuid IS NULL", "parent.tenant_id = NEW.tenant_id"),
    "DB lineage cannot fall back to a matching legacy id when both canonical UUIDs exist but differ",
)
record(
    "fact_hash_v1_v2_compatibility",
    all_in(src["fact"], "_HASH_FIELDS_V1", "_HASH_FIELDS_V2", "return self._HASH_FIELDS_V2 if self.staff_master_uuid else self._HASH_FIELDS_V1", "same_staff_identity"),
    "legacy sealed facts keep V1 hashes while canonical successors use V2",
)

write_checks = {
    "plan_write_uuid": (src["plan"], ["@transaction.atomic", "for_update=True", "staff_master_uuid=identity.staff_uuid"]),
    "request_write_uuid": (src["requests"], ["for_update=True", "staff_master_uuid=identity.staff_uuid"]),
    "enrollment_write_uuid": (src["enrollment"], ["staff_identity_q(identity)", "staff_master_uuid=identity.staff_uuid"]),
    "practice_assignment_write_uuid": (src["practice"], ["for_update=True", "staff_master_uuid=identity.staff_uuid"]),
    "development_output_write_uuid": (src["output"], ["for_update=True", "staff_master_uuid=identity.staff_uuid"]),
}
for name, (source, needles) in write_checks.items():
    record(name, all_in(source, *needles), "new core HR10 staff writes persist canonical HR03 UUID")

record(
    "approval_self_check_canonical",
    all_in(src["approval"], "def _is_self_approval", "applicant_uuid", "approver_staff_uuid")
    and src["approval"].count("ApprovalService._is_self_approval") >= 3,
    "approve/return/reject share the same canonical self-approval guard",
)
record(
    "record_routes_accept_uuid_and_legacy",
    '<str:staff_id>' in src["urls"] and '<str:staff_id>' in src["ui_urls"] and "staff_identity_q(identity)" in src["records"],
    "deep links accept UUID while old numeric ids remain resolvable through the adapter",
)
record(
    "ui_emits_canonical_staff_values",
    all_in(src["workbench"], '"value": str(item.id)') and "legacy_employee_id__isnull=False" not in src["workbench"]
    and "resolve_staff_identity" in src["views"],
    "new UI selections use HR03 UUID even for staff without legacy Employee ids",
)
record(
    "hr11_boundary_fail_closed",
    all_in(src["time"], "identity.legacy_employee_id", "HR11_LEGACY_ID_MAPPING_REQUIRED", "ScheduleConflictResult.SOURCE_UNAVAILABLE", "ProviderStatus.UNAVAILABLE"),
    "HR11 bigint compatibility is isolated at the provider boundary and missing mapping is not treated as no conflict",
)
record(
    "public_provider_dual_read",
    all_in(src["public"], "staff_master_uuid__in", "staff_master_uuid__isnull=True", "staff_master_id__in", "requested canonical HR03 staff ids"),
    "HR09/public evidence consumes canonical UUID and safely includes historic facts",
)
record(
    "public_provider_rejects_ambiguous_legacy_bridge",
    all_in(src["public"], "SOURCE_IDENTITY_MAPPING_AMBIGUOUS", "bridge_members", "ambiguous_legacy_ids"),
    "HR09 authority evidence never assigns a legacy-only fact through a duplicate Employee mapping",
)
record(
    "individual_excel_canonicalized",
    all_in(src["import_worker"], "staff_master_uuid", "staff_master_legacy_id", "AMBIGUOUS_LEGACY_MAPPING")
    and "HR03_UUID_CONTRACT_MISMATCH" not in src["import_worker"],
    "individual-plan Excel now writes real HR03 identity instead of being a permanent false-closed placeholder",
)
record(
    "fact_successor_upgrades_identity",
    all_in(src["authority"], "resolve_staff_identity", 'values["staff_master_uuid"] = identity.staff_uuid'),
    "a correction/revocation of mappable V1 history becomes a canonical V2 successor without rewriting the parent",
)
record(
    "further_study_writeback_prefers_uuid",
    all_in(src["further"], "staff_identity_key = case.staff_master_uuid or case.staff_master_id", "staff_master_id=str(staff_identity_key)"),
    "HR03 education writeback receives canonical UUID for new cases with a legacy fallback only for old rows",
)

hr10_api_text = "\n".join(text(path) for path in [
    "backend/hr10_development/api/plans.py",
    "backend/hr10_development/api/requests.py",
    "backend/hr10_development/api/practice.py",
    "backend/hr10_development/api/practice_process.py",
    "backend/hr10_development/api/development_records.py",
])
record(
    "no_direct_client_staff_int_cast",
    "int(body[\"staffMasterId\"])" not in hr10_api_text and "int(body.get(\"staffMasterId\"" not in hr10_api_text,
    "client staff ids are not forced back into the obsolete bigint contract",
)
record(
    "no_direct_api_legacy_lookup",
    "legacy_employee_id=staff_id" not in hr10_api_text,
    "public HR10 write APIs do not bypass the identity adapter",
)

regression = (
    text("backend/hr10_development/tests/test_excel_import_pipeline.py")
    + text("backend/hr10_development/tests/test_hr11_time_conflict_provider.py")
    + text("backend/hr10_development/tests/test_development_fact_authority.py")
    + text("backend/hr10_development/tests/test_public_identity_contract.py")
)
required_test_names = [
    "test_individual_plan_import_resolves_hr03_uuid_and_executes",
    "test_individual_plan_legacy_id_is_accepted_only_through_tenant_mapping",
    "test_canonical_uuid_resolves_to_hr11_legacy_boundary",
    "test_staff_without_legacy_hr11_mapping_is_source_unavailable",
    "test_duplicate_legacy_mapping_makes_canonical_identity_source_unavailable",
    "test_ambiguous_legacy_bridge_fails_closed_for_authority_evidence",
    "test_correction_is_sealed_successor_and_idempotent",
]
record(
    "targeted_regressions_present",
    all(name in regression for name in required_test_names),
    f"{len(required_test_names)} identity-specific Django regression cases are present",
)

passed = sum(item["ok"] for item in CHECKS)
result = {
    "gate": "HR10_STAFF_IDENTITY_STATIC",
    "status": "PASS" if passed == len(CHECKS) else "FAIL",
    "passed": passed,
    "total": len(CHECKS),
    "checks": CHECKS,
    "scopeNote": "Static/AST only. Real Django model-state, migration and MySQL trigger behavior must still run in QA.",
}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if result["status"] == "PASS" else 1)
