import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_hr_acceptance_gate.py"

spec = importlib.util.spec_from_file_location("round4_acceptance_gate", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class AcceptanceGateSafetyTests(unittest.TestCase):
    def test_rejects_production_like_project_names(self):
        for value in (
            "yueke_prod", "production-hr", "hr-live-qa",
            "yueke-productionqa", "hr-liveqa",
        ):
            with self.assertRaises(module.AcceptanceGateError):
                module._validate_project_name(value)

    def test_requires_acceptance_or_qa_namespace(self):
        with self.assertRaises(module.AcceptanceGateError):
            module._validate_project_name("yueke_hr_test")
        self.assertEqual(
            module._validate_project_name("yueke_hr_acceptance_123"),
            "yueke_hr_acceptance_123",
        )

    def test_generated_env_is_isolated_and_has_no_source_dotenv_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = module.RuntimePaths(
                root=root,
                env_file=root / "acceptance.env",
                backup_root=root / "backups",
                evidence_file=root / "evidence.json",
            )
            values = module._build_runtime_env(paths)
        self.assertEqual(values["HR_ACCEPTANCE_ISOLATED"], "YES")
        self.assertEqual(values["HORILLA_ENV"], "production")
        self.assertEqual(values["MYSQL_DATABASE"], "renshi_db")
        self.assertIn("@db:3306/renshi_db", values["DATABASE_URL"])
        self.assertIn("@redis:6379/0", values["REDIS_URL"])
        self.assertNotIn("change-me", "\n".join(values.values()).lower())
        self.assertGreaterEqual(len(values["SECRET_KEY"]), 50)
        self.assertNotIn("HR_BOOTSTRAP_ADMIN_PASSWORD", values)

    def test_plan_contains_database_backup_restore_and_cleanup(self):
        plan = "\n".join(module._redacted_plan("yueke_hr_acceptance_123"))
        for expected in (
            "MySQL 8.4",
            "HR01-HR18",
            "backup",
            "restore",
            "/ready/",
            "destroy",
        ):
            self.assertIn(expected, plan)

    def test_compose_overlay_never_changes_make_prod_path(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        acceptance = (ROOT / "docker-compose.acceptance.yml").read_text(encoding="utf-8")
        self.assertIn("acceptance-qa:", makefile)
        self.assertIn("run_hr_acceptance_gate.py", makefile)
        prod_block = makefile.split("prod:", 1)[1].split("acceptance-plan:", 1)[0]
        self.assertNotIn("docker-compose.acceptance.yml", prod_block)
        self.assertIn("HR_ACCEPTANCE_ENV_FILE", acceptance)
        for service in (
            "release", "web", "hr18-submission-worker", "hr18-exchange-worker",
            "legacy-scheduler", "employee-scheduler", "backup-scheduler",
        ):
            self.assertIn(f"  {service}:", acceptance)

    def test_command_display_redacts_secret_shapes(self):
        rendered = module._display_command([
            "docker", "run", "-e", "PASSWORD=secret-value",
            "mysql", "-psecret-value",
            "mysql://root:secret-value@db:3306/renshi_db",
        ])
        self.assertNotIn("secret-value", rendered)
        self.assertIn("<redacted>", rendered)


if __name__ == "__main__":
    unittest.main()
