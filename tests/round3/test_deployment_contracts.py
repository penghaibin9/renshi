import ast
import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_compose_preflight():
    path = ROOT / "scripts" / "check_prod_compose.py"
    spec = importlib.util.spec_from_file_location("check_prod_compose", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class ProductionDeploymentContractTests(unittest.TestCase):
    def test_release_uses_image_entrypoint_and_exact_prepare_command(self):
        text = (ROOT / "docker-compose.prod.yml").read_text()
        release = text.split("  release:\n", 1)[1].split("\n  web:\n", 1)[0]
        self.assertIn("image: renshi-web:latest", release)
        self.assertNotIn("entrypoint:", release)
        self.assertIn(
            'command: ["python", "manage.py", "prepare_runtime", "--migrate", "--collectstatic"]',
            release,
        )
        self.assertIn('MIGRATE_ON_START: "0"', release)
        self.assertIn('COLLECTSTATIC_ON_START: "0"', release)
        self.assertIn('CHECK_ON_START: "0"', release)

    def test_compose_preflight_enforces_override_capable_version_and_config(self):
        module = load_compose_preflight()
        good = subprocess.CompletedProcess([], 0, stdout="2.24.4\n", stderr="")
        parsed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(module, "_run", side_effect=[good, parsed]) as run:
            with patch.dict(os.environ, {"COMPOSE_COMMAND": "docker compose"}, clear=False):
                self.assertEqual(module.main(), 0)
        self.assertEqual(run.call_count, 2)

        old = subprocess.CompletedProcess([], 0, stdout="2.23.3\n", stderr="")
        with patch.object(module, "_run", return_value=old) as run:
            self.assertEqual(module.main(), 2)
        self.assertEqual(run.call_count, 1)

    def test_bootstrap_password_is_not_a_cli_argument(self):
        source = (ROOT / "backend/base/management/commands/bootstrap_production_admin.py").read_text()
        self.assertNotIn('add_argument("--password"', source)
        self.assertIn('PASSWORD_ENV = "HR_BOOTSTRAP_ADMIN_PASSWORD"', source)
        self.assertIn('transaction.atomic()', source)
        self.assertIn('PRODUCTION_BOOTSTRAP_COMPLETE', source)
        self.assertIn('Database is not empty', source)


class InitializationFailClosedContractTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "backend/base/views.py"
        self.source = self.path.read_text()
        self.tree = ast.parse(self.source)
        self.functions = {
            node.name: node for node in self.tree.body if isinstance(node, ast.FunctionDef)
        }

    @staticmethod
    def first_statement_after_docstring(fn):
        body = list(fn.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant
        ) and isinstance(body[0].value.value, str):
            body = body[1:]
        return body[0] if body else None

    def test_production_demo_loader_is_hidden(self):
        fn = self.functions["load_demo_database"]
        first = self.first_statement_after_docstring(fn)
        self.assertIsInstance(first, ast.If)
        rendered = ast.unparse(first.test)
        self.assertIn("not settings.DEBUG", rendered)
        self.assertIn("raise Http404", ast.unparse(first))
        self.assertIn("constant_time_compare", ast.get_source_segment(self.source, fn))

    def test_every_child_initialization_endpoint_requires_session_grant(self):
        guarded = [
            "initialize_database_user",
            "initialize_database_company",
            "initialize_database_department",
            "initialize_department_edit",
            "initialize_department_delete",
            "initialize_database_job_position",
            "initialize_job_position_edit",
            "initialize_job_position_delete",
        ]
        for name in guarded:
            with self.subTest(name=name):
                fn = self.functions[name]
                first = self.first_statement_after_docstring(fn)
                self.assertIsInstance(first, ast.Expr)
                self.assertEqual(ast.unparse(first), "_require_database_initialization_access(request)")


class RetirementReplanContractTests(unittest.TestCase):
    def test_successor_replan_reopens_review_but_blocks_downstream_facts(self):
        case_source = (ROOT / "backend/hr_exit/services/case_service.py").read_text()
        flex_source = (ROOT / "backend/hr_exit/services/flex_service.py").read_text()
        self.assertIn("def revise_retirement_plan_for_successor", case_source)
        self.assertIn("ExitCase.Status.SETTLEMENT", case_source)
        self.assertIn("ExitCase.Status.EFFECT_PENDING", case_source)
        self.assertIn("ExitCase.Status.EFFECTIVE", case_source)
        self.assertIn("EXIT_RETIREMENT_HANDOVER_REVISION_REQUIRED", case_source)
        self.assertIn("case.status = ExitCase.Status.RETURNED", case_source)
        self.assertIn("EXIT_CASE_REPLANNED", flex_source)
        self.assertIn('"previousPlan": prior', flex_source)


if __name__ == "__main__":
    unittest.main()
