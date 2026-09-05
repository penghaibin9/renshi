"""Contract tests for the system-settings production acceptance harness."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SystemSettingsBrowserGateContractTests(SimpleTestCase):
    def setUp(self):
        repo_root = Path(settings.BASE_DIR).parent
        self.browser_source = (
            repo_root / "scripts" / "system_settings_browser.py"
        ).read_text(encoding="utf-8")
        self.workflow_source = (
            repo_root
            / ".github"
            / "workflows"
            / "system-settings-browser.yml"
        ).read_text(encoding="utf-8")

    def test_positive_path_uses_production_login_and_top_right_click(self):
        self.assertIn("/login/", self.browser_source)
        self.assertIn("sessionid", self.browser_source)
        self.assertIn("click_top_right_settings", self.browser_source)
        self.assertIn("top-right user menu", self.browser_source)
        self.assertNotIn("force_login", self.browser_source)
        self.assertNotIn("django.test.Client", self.browser_source)

    def test_save_path_requires_browser_reload_and_exact_persistence(self):
        self.assertIn("try_persist_one_setting", self.browser_source)
        self.assertIn("persistedValue", self.browser_source)
        self.assertIn("newValue", self.browser_source)
        self.assertIn("page.goto(verify_url", self.browser_source)
        self.assertIn("Seal browser persistence in MySQL", self.workflow_source)
        self.assertIn("information_schema.columns", self.workflow_source)
        self.assertIn("mysql-seal.json", self.workflow_source)

    def test_negative_path_uses_an_independent_ordinary_role(self):
        self.assertIn("BUSINESS_USERNAME", self.browser_source)
        self.assertIn("ordinary business user", self.browser_source)
        self.assertIn("writable system settings surface", self.browser_source)
        self.assertIn("CompanyGroupAssignment", self.workflow_source)
        self.assertIn("SETTINGS_BUSINESS_USERNAME", self.workflow_source)

    def test_workflow_runs_real_mysql_and_chromium(self):
        self.assertIn("mysql:8.4", self.workflow_source)
        self.assertIn("python -m playwright install", self.workflow_source)
        self.assertIn("python manage.py migrate --check", self.workflow_source)
        self.assertIn("python scripts/system_settings_browser.py", self.workflow_source)
        self.assertIn("django-runserver.log", self.workflow_source)
        self.assertIn("readiness.json", self.workflow_source)
