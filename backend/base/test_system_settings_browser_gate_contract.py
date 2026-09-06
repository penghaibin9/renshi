"""Self-check the real settings browser harness without starting its fixtures.

These structural contracts do not replace Chromium/MySQL acceptance. They keep
seed producers, browser consumers and the independent persistence seal aligned.
"""

import ast
from pathlib import Path
import unittest

import yaml


class SystemSettingsBrowserGateContractTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.browser_source = (root / "scripts/system_settings_browser.py").read_text(encoding="utf-8")
        self.browser_tree = ast.parse(self.browser_source)
        self.functions = {
            node.name: ast.get_source_segment(self.browser_source, node)
            for node in self.browser_tree.body if isinstance(node, ast.FunctionDef)
        }
        self.workflow_source = (root / ".github/workflows/system-settings-browser.yml").read_text(encoding="utf-8")
        self.workflow = yaml.safe_load(self.workflow_source)
        self.steps = {
            step["name"]: step
            for step in self.workflow["jobs"]["top-right-settings-and-tenant-boundaries"]["steps"]
            if "name" in step
        }
        self.seed_source = self.python_step("Seed two schools and three ordinary browser roles")
        self.seal_source = self.python_step("Seal settings facts directly from MySQL")
        self.seed_tree = ast.parse(self.seed_source)
        self.seal_tree = ast.parse(self.seal_source)

    def python_step(self, name):
        command = self.steps[name]["run"]
        self.assertIn("python manage.py shell <<'PY'\n", command)
        source = command.split("python manage.py shell <<'PY'\n", 1)[1]
        return source.rsplit("\nPY", 1)[0]

    def test_positive_path_uses_production_login_and_top_right_click(self):
        login = self.functions["authenticated_page"]
        for marker in ("/login/", "sessionid", "#username", "#password", "submit.click()",
                       "browser.new_context", "context.tracing.start", "context.tracing.stop"):
            self.assertIn(marker, login)
        self.assertIn("gear_links(page)", self.functions["open_settings"])
        self.assertIn("links.first.click()", self.functions["open_settings"])
        self.assertIn("playwright.chromium.launch", self.functions["main"])
        for bypass in ("force_login", "django.test.Client", "create_superuser"):
            self.assertNotIn(bypass, self.browser_source + self.seed_source)

    def test_save_path_requires_browser_reload_and_exact_persistence(self):
        save = self.functions["save_preferences"]
        self.assertIn("page.reload(", save)
        for marker in ('"#id_pagination"', '"#dateFormat"', '"#timeFormat"'):
            self.assertIn(marker, save)
        self.assertEqual(save.count(".input_value()"), 3)
        edit = self.functions["edit_school"]
        for marker in ("form.locator", '.fill(name)', '.fill(address)', "page.goto(",
                       "open_company_settings(", "address in", '"POST"'):
            self.assertIn(marker, edit)
        for marker in ('[hx-get^=', '.select_option("China")', '.select_option("Hunan")',
                       'form.checkValidity()', 'page.expect_navigation(', 'navigation.value.status == 200'):
            self.assertIn(marker, edit)
        for assertion in (
            'assert school_a.company == seed["school_a_updated_name"]',
            'assert school_a.address == seed["school_a_updated_address"]',
            'assert school_b.company == seed["school_b_name"]',
            'assert school_b.address == seed["school_b_original_address"]',
            'assert school_a.date_format == "YYYY-MM-DD"',
            'assert school_b.date_format == "DD/MM/YYYY"',
            "assert admin_a_pagination.pagination == 37",
            "assert admin_b_pagination.pagination == 61",
        ):
            self.assertIn(assertion, self.seal_source)
        self.assertIn("mysql-seal.json", self.seal_source)
        self.assertIn("PRODUCT_HEAD_SHA", self.seal_source)
        self.assertIn('["git", "rev-parse", "HEAD"]', self.seal_source)

    def test_negative_path_uses_an_independent_ordinary_role(self):
        assignment = next(node for node in self.browser_tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "ROLE_CREDENTIALS"
                                  for target in node.targets))
        self.assertEqual({ast.literal_eval(key) for key in assignment.value.keys},
                         {"school_a_admin", "school_a_teacher", "school_b_admin"})
        self.assertEqual(self.functions["main"].count("with authenticated_page(browser, role)"), 3)
        self.assertIn("CompanyGroupAssignment", self.seed_source)
        self.assertIn("User.objects.create_user(", self.seed_source)
        for marker in ('"settings-gear-not-rendered"', '"company-list-denied"',
                       '"cross-tenant-company-form-concealed"', '"status"] == 403',
                       "response.status == 404"):
            self.assertIn(marker, self.functions["main"])

    def test_workflow_runs_real_mysql_and_chromium(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        for marker in ("mysql:8.4", "python -m playwright install", "python manage.py migrate --check",
                       "python scripts/system_settings_browser.py", "django-runserver.log", "readiness.json",
                       "base.test_system_settings_browser_gate_contract"):
            self.assertIn(marker, self.workflow_source)
        self.assertNotIn("continue-on-error", self.workflow_source)
        self.assertEqual(self.steps["Upload System Settings browser evidence"]["if"], "always()")

    def test_seed_declares_every_key_consumed_by_browser_and_database_seal(self):
        dictionaries = [node for node in ast.walk(self.seed_tree) if isinstance(node, ast.Dict)]
        declared = next({ast.literal_eval(key) for key in node.keys if isinstance(key, ast.Constant)}
                        for node in dictionaries
                        if any(isinstance(key, ast.Constant) and key.value == "school_a_id" for key in node.keys))
        consumed = {
            node.slice.value for tree in (self.browser_tree, self.seal_tree) for node in ast.walk(tree)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == "seed" and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        }
        self.assertFalse(consumed - declared, "Missing seed keys: " + repr(consumed - declared))
        self.assertTrue({"school_a_updated_name", "school_a_updated_address", "school_b_original_address"} <= declared)

    def test_evidence_matrix_keeps_all_roles_and_rejects_duplicate_rows(self):
        node = next(node for node in self.seal_tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets))
        matrix = ast.literal_eval(node.value)
        self.assertEqual(len(matrix), 21)
        self.assertEqual(matrix[("school_a_admin", "school-profile-edited-and-reloaded")], 200)
        self.assertEqual(matrix[("school_a_teacher", "company-list-denied")], 403)
        self.assertEqual(matrix[("school_b_admin", "cross-tenant-company-form-concealed")], 404)
        self.assertEqual(sum(role == "school_a_admin" for role, _ in matrix), 7)
        self.assertEqual(sum(role == "school_a_teacher" for role, _ in matrix), 7)
        self.assertEqual(sum(role == "school_b_admin" for role, _ in matrix), 7)
        self.assertIn("actual == expected and len(evidence) == len(expected)", self.seal_source)
        self.assertIn('"school-profile-edited-and-reloaded"', self.functions["main"])
