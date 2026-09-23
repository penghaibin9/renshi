import ast
import importlib.util
import io
import sys
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def load_keyring_module():
    path = ROOT / "backend/horilla/security/field_keyring.py"
    spec = importlib.util.spec_from_file_location("round7_field_keyring", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FieldSecurityLaunchTests(unittest.TestCase):
    def test_keyring_encrypt_decrypt_and_rotation(self):
        mod = load_keyring_module()
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()
        old = f"old:{old_key}"
        cipher = mod.encrypt_text(old, "ID-123456", prefix="test:v2")
        rotated = f"new:{new_key},old:{old_key}"
        self.assertEqual(mod.decrypt_text(rotated, cipher, prefix="test:v2"), "ID-123456")
        self.assertTrue(mod.needs_rewrap(cipher, rotated, prefix="test:v2"))
        rewritten = mod.encrypt_text(rotated, "ID-123456", prefix="test:v2")
        self.assertFalse(mod.needs_rewrap(rewritten, rotated, prefix="test:v2"))

    def test_keyed_fingerprint_is_tenant_and_namespace_scoped(self):
        mod = load_keyring_module()
        secret = "x" * 48
        a = mod.keyed_fingerprint(secret, namespace="hr03.document", tenant_id=1, normalized_value="ABC")
        b = mod.keyed_fingerprint(secret, namespace="hr03.document", tenant_id=2, normalized_value="ABC")
        c = mod.keyed_fingerprint(secret, namespace="hr04.candidate", tenant_id=1, normalized_value="ABC")
        self.assertEqual(len(a), 64)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_sensitive_domains_use_separated_field_secrets(self):
        staff = text("backend/hr_staff/services/crypto.py")
        recruit = text("backend/hr_recruitment/security.py")
        onboarding = text("backend/hr_onboarding/services/security.py")
        qualification = text("backend/hr_qualification/security.py")
        material = text("backend/hr_external/services/material_service.py")
        for source in (staff, recruit, onboarding, qualification):
            self.assertIn("FIELD_ENCRYPTION_KEYS", source)
        for source in (staff, recruit, qualification):
            self.assertIn("FIELD_FINGERPRINT_KEY", source)
        self.assertIn("HR08_TICKET_SIGNING_KEY", material)

    def test_production_gate_rejects_secret_reuse(self):
        source = text("backend/horilla/settings/security.py")
        self.assertIn("must not reuse Django, backup, fingerprint or ticket-signing secrets", source)
        self.assertIn("FIELD_FINGERPRINT_KEY must not reuse", source)
        self.assertIn("HR08_TICKET_SIGNING_KEY must not reuse", source)

    def test_sensitive_field_rewrap_command_is_wired_into_acceptance(self):
        command = text("backend/hr_staff/management/commands/rotate_hr_field_security.py")
        gate = text("scripts/run_hr_acceptance_gate.py")
        for domain in ("_hr03", "_hr04", "_hr05", "_hr09"):
            self.assertIn(f"def {domain}", command)
        self.assertIn("hr04_hash_only_unresolved", command)
        self.assertIn("rotate_hr_field_security", gate)
        self.assertIn("--check", gate)


class DurableExcelLaunchTests(unittest.TestCase):
    def test_excel_import_has_database_job_and_row_ledger(self):
        model = text("backend/hr_onboarding/models/import_job.py")
        migration = text("backend/hr_onboarding/migrations/0017_durable_excel_import_ledger.py")
        for token in ("HrOnboardingImportJob", "HrOnboardingImportRow", "source_sha256", "commit_started_at"):
            self.assertIn(token, model)
            self.assertIn(token, migration)

    def test_excel_api_no_longer_uses_process_global_jobs(self):
        source = text("backend/hr_onboarding/api/excel.py")
        self.assertNotIn("_jobs =", source)
        self.assertIn("stage_persisted_import", source)
        self.assertIn("confirm_persisted_import", source)
        self.assertIn("excel_job_status", source)
        self.assertIn("status=202", source)

    def test_excel_import_limits_archive_and_rows(self):
        source = text("backend/hr_onboarding/services/excel_service.py")
        for token in (
            "MAX_IMPORT_BYTES = 10 * 1024 * 1024",
            "MAX_IMPORT_ROWS = 5000",
            "MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024",
            "MAX_XLSX_ENTRIES = 2000",
            "def _validate_xlsx_archive",
            '"[Content_Types].xml"',
        ):
            self.assertIn(token, source)

    def test_non_legacy_excel_rows_require_real_source_id(self):
        source = text("backend/hr_onboarding/services/excel_service.py")
        self.assertIn("st != CaseSourceType.LEGACY_MIGRATION", source)
        self.assertIn('f"excel:{job.id}:{row.row_no}"', source)
        self.assertIn('idempotency_key=f"hr05-excel:{job.id}:{row.row_no}"', source)


class AuthorityAndGoLiveTests(unittest.TestCase):
    def test_hr09_cutover_uses_shared_authority_ledger(self):
        service = text("backend/hr_qualification/services/authority_mode_service.py")
        command = text("backend/hr_qualification/management/commands/hr09_switch_authority.py")
        self.assertIn("HrAuthorityCutover", service)
        self.assertIn('domain = "QUALIFICATION"', service)
        self.assertIn("verification report id", service)
        self.assertNotIn("tenant_id=0", command)
        self.assertNotIn("in-memory", command.lower())
        self.assertIn("HR09_AUTHORITY_CUTOVER_OK", command)

    def test_field_rewrap_is_tenant_scoped_for_single_school_launch(self):
        source = text("backend/hr_staff/management/commands/rotate_hr_field_security.py")
        audit = text("backend/hr_control_center/management/commands/hr_go_live_audit.py")
        self.assertIn('"--tenant"', source)
        self.assertGreaterEqual(source.count("qs = qs.filter(tenant_id=tenant_id)"), 4)
        self.assertIn("tenant=tenant_id", audit)

    def test_makefile_exposes_single_beginner_go_live_command(self):
        source = text("Makefile")
        self.assertIn("go-live-audit: prod-preflight", source)
        self.assertIn("TENANT_ID", source)
        self.assertIn("hr_go_live_audit --tenant", source)

    def test_go_live_audit_fails_closed_when_hr09_cutover_state_cannot_be_read(self):
        source = text("backend/hr_control_center/management/commands/hr_go_live_audit.py")
        self.assertIn("HR09 cutover state unavailable", source)
        self.assertIn('"HR09_AUTHORITY_CUTOVER"', source)
        self.assertIn('"BLOCKER"', source)

    def test_runbook_scopes_sensitive_field_rotation_to_the_target_school(self):
        source = text("docs/PRODUCTION_RUNBOOK.md")
        self.assertIn("rotate_hr_field_security --tenant 真实租户ID", source)
        self.assertIn("make go-live-audit TENANT_ID=真实租户ID", source)

    def test_go_live_audit_aggregates_real_runtime_blockers(self):
        source = text("backend/hr_control_center/management/commands/hr_go_live_audit.py")
        for token in (
            "SEPARATED_HR_SECRETS",
            "HR_FIELD_SECURITY_REWRAP",
            "HR01_HR18_AUTHORITY_GATE",
            "HR05_IMPORT_STALE_COMMIT",
            "HR03_OUTBOX_DEAD",
            "HR05_OUTBOX_DROPPED",
            "HR06_OUTBOX_DROPPED",
            "HR09_AUTHORITY_CUTOVER",
            "READY_FOR_RUNTIME_ACCEPTANCE",
        ):
            self.assertIn(token, source)
        self.assertNotIn("objects.create(", source)
        self.assertNotIn("objects.update(", source)

    def test_china_education_standards_remain_current(self):
        source = text("backend/hr_data/standards/china_education.py")
        self.assertIn('"code": "JY/T 0637-2022"', source)
        self.assertIn('"code": "JY/T 0661-2025"', source)
        self.assertIn('"wholeUniversityStaffMinimumLevel": "L3"', source)

    def test_new_python_sources_parse(self):
        paths = (
            "backend/horilla/security/field_keyring.py",
            "backend/hr_staff/management/commands/rotate_hr_field_security.py",
            "backend/hr_onboarding/models/import_job.py",
            "backend/hr_onboarding/services/excel_service.py",
            "backend/hr_control_center/management/commands/hr_go_live_audit.py",
            "backend/hr_qualification/services/authority_mode_service.py",
            "backend/hr_qualification/management/commands/hr09_switch_authority.py",
            "backend/hr_recruitment/security.py",
        )
        for path in paths:
            ast.parse(text(path), filename=path)


if __name__ == "__main__":
    unittest.main()

class FinalPrelaunchHardeningTests(unittest.TestCase):
    def test_hr04_legacy_hash_keeps_exact_round6_input_compatibility(self):
        source = text("backend/hr_recruitment/security.py")
        self.assertIn('value = str(national_id or "").strip()', source)
        self.assertIn("normalized_legacy_candidate_id_hash", source)
        self.assertIn("legacy_raw", source)
        self.assertIn("legacy_normalized", source)

    def test_hr05_sensitive_encryption_fails_closed(self):
        source = text("backend/hr_onboarding/services/security.py")
        block = source[source.index("def encrypt_sensitive_value"):source.index("def decrypt_sensitive_value")]
        self.assertIn('logger.exception("sensitive encrypt failed")', block)
        self.assertIn("raise", block)
        self.assertNotIn('logger.exception("sensitive encrypt failed")\n        return {}', block)

    def test_excel_rejects_bad_headers_empty_workbook_and_windows_archive_escape(self):
        source = text("backend/hr_onboarding/services/excel_service.py")
        for token in (
            "EXCEL_DUPLICATE_HEADER",
            "EXCEL_REQUIRED_HEADER_MISSING",
            "EXCEL_EMPTY_WORKBOOK",
            '"\\\\" in name',
        ):
            self.assertIn(token, source)

    def test_hr05_outbox_has_real_production_worker_and_authority_receipt_handlers(self):
        handlers = text("backend/hr_onboarding/jobs/production_outbox_handlers.py")
        command = text("backend/hr_onboarding/management/commands/hr05_dispatch_outbox.py")
        compose = text("docker-compose.yml")
        prod = text("docker-compose.prod.yml")
        for event in (
            "StaffActivated",
            "ProbationConfirmed",
            "ProbationFailed",
            "ActivationFactCorrected",
            "ActivationFactRevoked",
        ):
            self.assertIn(event, handlers)
        self.assertIn("calculate_content_hash", handlers)
        self.assertIn("build_production_registry", command)
        self.assertIn('write_worker_heartbeat("hr05-outbox")', command)
        self.assertIn("--watch", command)
        self.assertIn("hr05-outbox-worker", compose)
        self.assertIn("hr05-outbox-worker", prod)
        import_worker = text("backend/hr_onboarding/management/commands/hr05_run_excel_imports.py")
        self.assertIn("commit_persisted_import", import_worker)
        self.assertIn('write_worker_heartbeat("hr05-import")', import_worker)
        self.assertIn("hr05-import-worker", compose)
        self.assertIn("hr05-import-worker", prod)

    def test_go_live_audit_blocks_stalled_or_dead_runtime_queues_and_missing_workers(self):
        source = text("backend/hr_control_center/management/commands/hr_go_live_audit.py")
        for token in (
            "HR05_OUTBOX_STALE_PENDING",
            "HR05_OUTBOX_FAILED",
            "HR18_SUBMISSION_DEAD",
            "HR18_EXCHANGE_DEAD_LETTER",
            "HR08_PROVISIONING_FAILED",
            '"hr05-outbox": 120',
            '"backup-scheduler": 180',
        ):
            self.assertIn(token, source)


def test_hr05_async_import_preserves_confirming_actor():
    model = text("backend/hr_onboarding/models/import_job.py")
    service = text("backend/hr_onboarding/services/excel_service.py")
    worker = text("backend/hr_onboarding/management/commands/hr05_run_excel_imports.py")
    assert "confirmed_by = models.BigIntegerField" in model
    assert "confirmed_at = models.DateTimeField" in model
    assert "job.confirmed_by = actor_user_id" in service
    assert "confirmed_by if confirmed_by is not None else uploaded_by" in worker
