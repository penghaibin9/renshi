import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Hr10CanonicalStaffIdentityContracts(unittest.TestCase):
    def test_static_identity_gate_is_green(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_hr10_staff_identity_contract.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["passed"], payload["total"])

    def test_import_gate_is_still_green_after_identity_upgrade(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_hr10_import_contract.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload["status"], "PASS")

    def test_mysql_migration_is_split_at_failure_boundaries(self):
        m26 = (ROOT / "backend/hr10_development/migrations/0026_canonical_hr03_staff_uuid.py").read_text(encoding="utf-8")
        m27 = (ROOT / "backend/hr10_development/migrations/0027_backfill_hr10_staff_uuid.py").read_text(encoding="utf-8")
        m28 = (ROOT / "backend/hr10_development/migrations/0028_hr10_staff_identity_guards.py").read_text(encoding="utf-8")
        self.assertNotIn("RunPython", m26)
        self.assertIn("_collect_required_mappings", m27)
        self.assertIn("SeparateDatabaseAndState", m28)
        self.assertIn("get_constraints", m28)

    def test_sealed_fact_legacy_hash_contract_remains_explicit(self):
        source = (ROOT / "backend/hr10_development/models/development_fact.py").read_text(encoding="utf-8")
        self.assertIn("_HASH_FIELDS_V1", source)
        self.assertIn("_HASH_FIELDS_V2", source)
        self.assertIn("if self.staff_master_uuid", source)

    def test_hr11_legacy_id_is_boundary_only(self):
        source = (ROOT / "backend/hr10_development/providers/time_provider.py").read_text(encoding="utf-8")
        self.assertIn("HR11_LEGACY_ID_MAPPING_REQUIRED", source)
        self.assertIn("identity.legacy_employee_id", source)
        self.assertIn("ProviderStatus.UNAVAILABLE", source)


if __name__ == "__main__":
    unittest.main()
