#!/usr/bin/env python3
"""Static procurement-grade data portability gate for Round11.

This validates source contracts without Django/MySQL. Runtime release still
requires a real MySQL create -> verify -> restore drill in an isolated QA env.
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
    "helper": "backend/horilla_backup/handover.py",
    "create": "backend/horilla_backup/management/commands/create_school_handover_package.py",
    "verify": "backend/horilla_backup/management/commands/verify_school_handover_package.py",
    "restore": "backend/horilla_backup/management/commands/restore_school_handover_package.py",
    "settings": "backend/horilla/settings/base.py",
    "compose": "docker-compose.prod.yml",
    "env": ".env.dist",
    "runbook": "docs/PRODUCTION_RUNBOOK.md",
    "pure_tests": "tests/round11/test_school_handover_contract.py",
    "acceptance": "scripts/run_hr_acceptance_gate.py",
}
src = {key: text(rel) for key, rel in paths.items()}

for key in ("helper", "create", "verify", "restore", "settings", "pure_tests", "acceptance"):
    try:
        ast.parse(src[key], filename=paths[key])
        record(f"ast:{key}", True, paths[key])
    except SyntaxError as exc:
        record(f"ast:{key}", False, f"{paths[key]}: {exc}")

record(
    "handover_is_separate_from_encrypted_dr_backup",
    has_all(
        src["helper"],
        'HANDOVER_FORMAT = "renshi-school-handover-v1"',
        "deliberately separate from encrypted production backups",
    )
    and "PRODUCTION_BACKUP_ENCRYPTION_KEY" not in src["create"],
    "school portability is a separate open-format path, not a renamed encrypted DR backup",
)
record(
    "sensitive_export_requires_explicit_ack",
    has_all(
        src["helper"],
        'HANDOVER_CONFIRMATION = "I_UNDERSTAND_THIS_EXPORT_CONTAINS_SENSITIVE_HR_DATA"',
    )
    and has_all(
        src["create"],
        'parser.add_argument("--recipient", required=True)',
        'parser.add_argument("--purpose", required=True)',
        'parser.add_argument("--operator", required=True)',
        'parser.add_argument("--confirm-sensitive-export", required=True)',
        'options["confirm_sensitive_export"] != HANDOVER_CONFIRMATION',
    ),
    "full HR export cannot run silently or anonymously",
)
record(
    "open_standard_artifacts_are_complete",
    has_all(
        src["helper"],
        '"database.sql"',
        '"media.tar.gz"',
        '"schema_dictionary.csv"',
        '"schema_dictionary.json"',
        '"table_row_counts.csv"',
        '"table_row_counts.json"',
        '"migration_state.json"',
        '"api_route_inventory.csv"',
        '"configuration_catalog.csv"',
        '"configuration_catalog.json"',
        '"interface_mapping_catalog.json"',
        '"runtime_configuration.json"',
        '"secret_handover_requirements.json"',
        '"README-HANDOVER.txt"',
    )
    and has_all(
        src["create"],
        '"database": "plain MySQL logical SQL dump"',
        '"media": "POSIX-compatible tar.gz"',
        '"data_dictionary": ["UTF-8 CSV", "JSON"]',
        '"proprietary_encryption_required_to_restore": False',
    ),
    "database, files, dictionary, migration state, API inventory and handover instructions use standard formats",
)
record(
    "database_dump_reuses_restorable_mysql_path",
    has_all(src["create"], "dump_mysql_db(", 'output_file=database_path'),
    "handover uses the same tested logical dump primitive as DR backup, without wrapping it in proprietary encryption",
)
record(
    "schema_dictionary_is_generated_from_information_schema",
    has_all(
        src["helper"],
        "FROM information_schema.COLUMNS",
        "TABLE_SCHEMA = DATABASE()",
        "csv.DictWriter",
        "json.dumps(rows",
    ),
    "recipient receives explicit field-level database structure in CSV and JSON",
)
record(
    "exact_table_row_counts_are_exported_and_rechecked",
    has_all(
        src["helper"],
        "def write_dump_row_counts",
        'prefix = "INSERT INTO `"',
        '"row_count_source"',
        '"row_count_table_count"',
        '"row_count_total_rows"',
    )
    and has_all(
        src["create"],
        "write_dump_row_counts(",
        'staging / "table_row_counts.csv"',
        'staging / "table_row_counts.json"',
    )
    and has_all(
        src["restore"],
        '"table_row_counts.json"',
        "post-restore exact row-count mismatch",
        "post-restore total row count mismatch",
    ),
    "handover restore validates exact base-table row counts instead of accepting a schema-only partial import",
)
record(
    "migration_state_is_exported",
    has_all(src["helper"], "FROM django_migrations", '"migration_count"'),
    "restore target can compare migration state rather than trusting the package label",
)
record(
    "api_inventory_is_exported",
    has_all(src["helper"], "def write_api_route_inventory", '"route"', '"name"', '"view"'),
    "current URL surface is inventoried in a reusable CSV",
)
record(
    "rule_and_mapping_configuration_are_human_readable",
    has_all(
        src["helper"],
        "def write_configuration_catalog",
        'keywords = ("rule", "config", "setting", "policy", "mapping", "cycle", "dictionary")',
        '"content_location": "database.sql"',
        "def write_interface_mapping_catalog",
        "hr18_exchange_target_mapping_version",
        '"mapping": mapping',
        '"expected_receipt": bool(raw[9])',
    )
    and has_all(
        src["create"],
        'staging / "configuration_catalog.csv"',
        'staging / "configuration_catalog.json"',
        'staging / "interface_mapping_catalog.json"',
    ),
    "rule/config tables and non-secret HR18 field mappings are separately indexed instead of being buried only in SQL",
)
record(
    "runtime_config_excludes_secret_values",
    has_all(
        src["helper"],
        '"secrets_included": False',
        '"database password"',
        '"Django SECRET_KEY"',
        '"field-encryption keys"',
        '"third-party access tokens"',
    )
    and "DATABASES[\"default\"][\"PASSWORD\"]" not in src["helper"],
    "handover documents topology/configuration without embedding runtime secrets",
)
record(
    "encrypted_field_keys_are_not_vendor_lock",
    has_all(
        src["helper"],
        '"FIELD_ENCRYPTION_KEYS"',
        '"TRANSFER_SEPARATELY"',
        '"configured_key_ids"',
        '"contains_secret_values": False',
        '"FIELD_FINGERPRINT_KEY"',
        '"TRANSFER_SEPARATELY_OR_CONTROLLED_REINDEX"',
    )
    and has_all(
        src["runbook"],
        "FIELD_ENCRYPTION_KEYS 必须通过学校控制的独立安全通道单独交接",
        "包内只记录 Key ID，不记录密钥值",
    ),
    "ciphertext remains readable after supplier exit because required key material has an explicit separate-handover contract",
)
record(
    "handover_root_is_not_web_accessible",
    has_all(
        src["helper"],
        "def assert_isolated_path",
        "must be isolated from public/static/media/source web paths",
    )
    and has_all(
        src["create"],
        "def _validate_private_roots",
        "settings.MEDIA_ROOT",
        "settings.STATIC_ROOT",
        'Path(settings.REPO_ROOT) / "frontend"',
        'label="SCHOOL_HANDOVER_ROOT"',
        'label="SCHOOL_HANDOVER_RECEIPT_ROOT"',
        "must be separate paths",
    )
    and 'os.chmod(root, 0o700)' in src["create"],
    "plaintext portability packages and receipts cannot be written under public/static/media/source paths",
)
record(
    "package_and_checksum_are_owner_only",
    src["create"].count("0o600") >= 3
    and "sha256_file(final_package)" in src["create"]
    and 'final_checksum.write_text(' in src["create"],
    "package artifacts and detached checksum are produced with restricted permissions",
)
record(
    "detached_package_checksum_is_mandatory_for_verify_and_restore",
    has_all(
        src["helper"],
        "def verify_detached_checksum",
        "missing detached checksum",
        "Detached checksum mismatch",
        "sha256_file(package)",
    )
    and "verify_detached_checksum(package)" in src["verify"]
    and "verify_detached_checksum(package)" in src["restore"],
    "accidental or unauthorized package-byte changes fail before extraction or restore",
)
record(
    "manifest_covers_every_file",
    has_all(
        src["create"],
        'if path.is_file() and path.name != "manifest.json"',
        "artifacts[relative] = artifact_metadata(path)",
    )
    and has_all(
        src["helper"],
        "actual - allowed",
        "unmanifested files",
        "artifact size mismatch",
        "artifact checksum mismatch",
    ),
    "verification fails on missing, modified or extra package files",
)
record(
    "archive_extraction_is_path_safe",
    has_all(
        src["helper"],
        "not (member.isfile() or member.isdir()) or member.issparse()",
        'value.startswith("/")',
        'part == ".."',
        "Handover extraction requires an empty private destination",
        "duplicate/aliased paths",
        "file/directory collisions",
        "Handover archive exceeds resource limits",
    ),
    "outer package rejects path traversal, links and device members",
)
record(
    "nested_media_archive_is_verified",
    has_all(src["helper"], 'inspect_archive(Path(extracted_root) / "media.tar.gz")'),
    "a checksummed but structurally unsafe media tar cannot pass verify",
)
record(
    "source_delivery_is_explicit_and_separate",
    has_all(
        src["create"],
        '"source_delivery"',
        '"included": False',
        '"required_separately": True',
        "matching signed source release separately",
    ),
    "data handover does not falsely claim source code is embedded; signed source release remains a separate contract deliverable",
)
record(
    "restore_target_must_be_separate_empty_and_confirmed",
    has_all(
        src["restore"],
        '--target-database',
        '--confirm-target',
        'options["confirm_target"] != target',
        'target.casefold() == source_database.casefold()',
        "Refusing to restore over the live configured database",
        "target database must be empty",
        'HANDOVER_RESTORE_CONFIRMATION',
    ),
    "restore cannot overwrite production or a non-empty target",
)
record(
    "restore_password_never_enters_argv",
    has_all(
        src["restore"],
        'password = os.environ.get("RESTORE_DATABASE_PASSWORD", "")',
        'environment["MYSQL_PWD"] = password',
    )
    and "--password" not in src["restore"],
    "restore credential is passed through child environment rather than process argv",
)
record(
    "media_is_prevalidated_before_database_mutation",
    src["restore"].index("_prepare_media_archive(") < src["restore"].index("_restore_database(")
    and has_all(
        src["restore"],
        "safe_extract_archive(archive_path, prepared)",
    ),
    "malformed media fails before MySQL import begins",
)
record(
    "restore_postcheck_compares_source_counts",
    has_all(
        src["restore"],
        "post-restore table count mismatch",
        "post-restore migration count mismatch",
        'manifest.get("stats", {}).get("table_count"',
        'manifest.get("stats", {}).get("migration_count"',
    ),
    "a nominal import is not accepted until table and migration counts match export metadata",
)
record(
    "receipts_are_append_only_jsonl",
    has_all(
        src["helper"],
        '"school-handover-receipts.jsonl"',
        "os.O_APPEND | os.O_CREAT | os.O_WRONLY",
    )
    and all(event in src[key] for key, event in (("create", '"CREATED"'), ("verify", '"VERIFIED"'), ("restore", '"RESTORED"'))),
    "create/verify/restore events append independent audit receipts",
)
record(
    "compose_persists_handover_and_receipts",
    has_all(
        src["compose"],
        "SCHOOL_HANDOVER_ROOT: /app/handover",
        "SCHOOL_HANDOVER_RECEIPT_ROOT: /app/handover-audit",
        "HANDOVER_STORAGE_PATH",
        "HANDOVER_AUDIT_STORAGE_PATH",
        ":/app/handover",
        ":/app/handover-audit",
    )
    and has_all(src["env"], "HANDOVER_STORAGE_PATH=", "HANDOVER_AUDIT_STORAGE_PATH="),
    "handover evidence survives container replacement and stays separate from DR backup storage",
)
record(
    "acceptance_harness_exercises_open_handover_restore",
    has_all(
        src["acceptance"],
        '"HANDOVER_STORAGE_PATH"',
        '"HANDOVER_AUDIT_STORAGE_PATH"',
        '"handover-create"',
        '"create_school_handover_package"',
        '"handover-verify"',
        '"verify_school_handover_package"',
        '"handover verify SHA-256 does not match the created package digest"',
        '"handover-restore"',
        '"restore_school_handover_package"',
        '"renshi_handover_restore_test"',
        '"handover-restored-migration-check"',
        '"handover-restore-schema-count"',
        'evidence["handoverPackage"]',
        'evidence["handoverSha256"]',
        'evidence["handoverSchemaTableCounts"]',
    ),
    "the production-shaped isolated acceptance harness must actually create, verify and restore the open handover package before release",
)
record(
    "runbook_has_create_verify_restore_and_failure_policy",
    has_all(
        src["runbook"],
        "学校数据与系统资料移交",
        "create_school_handover_package",
        "verify_school_handover_package",
        "restore_school_handover_package",
        "不得在半恢复库上继续重试",
        "不允许把日常 AES 灾备包冒充学校移交包",
    ),
    "operator procedure distinguishes DR from supplier-exit portability and documents MySQL non-transactional restore failure handling",
)

passed = sum(1 for item in CHECKS if item["ok"])
result = {
    "gate": "SCHOOL_HANDOVER_PORTABILITY_CONTRACT_STATIC",
    "status": "PASS" if passed == len(CHECKS) else "FAIL",
    "passed": passed,
    "total": len(CHECKS),
    "checks": CHECKS,
    "scopeNote": (
        "Static procurement-portability gate only. Release still requires a real MySQL export, "
        "package verification, isolated restore, restored-web readiness and sampled business facts."
    ),
}
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if result["status"] == "PASS" else 1)
