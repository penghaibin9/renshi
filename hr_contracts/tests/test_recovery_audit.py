from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from hr_contracts import module_contract
from hr_contracts.recovery_audit import assert_recovery_gate_consistent, recovery_snapshot


class Hr07RecoveryAuditTests(SimpleTestCase):
    def test_incomplete_structure_cannot_be_reported_as_registerable(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            snapshot = recovery_snapshot(base_dir=root)

        self.assertFalse(snapshot["registrationAllowed"])
        self.assertIn("apps.py", snapshot["missing"])
        self.assertIn("models.py", snapshot["missing"])
        self.assertIn("migrations", snapshot["missing"])

    def test_current_contract_remains_fail_closed(self):
        snapshot = assert_recovery_gate_consistent()

        self.assertEqual(module_contract.RECOVERY_STATE, "INCOMPLETE")
        self.assertFalse(module_contract.SAFE_TO_REGISTER)
        self.assertFalse(snapshot["registrationAllowed"])
