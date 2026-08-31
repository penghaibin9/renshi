from pathlib import Path

from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase


class ExternalTeacherUiTemplateContractTests(SimpleTestCase):
    """Prevent HR08 runtime pages from falling back to the retired base.html shell."""

    RUNTIME_TEMPLATES = (
        "hr_external/templates/hr_external/external_teacher_list.html",
        "hr_external/templates/hr_external/external_teacher_pool.html",
        "hr_external/templates/hr_external/external_teacher_profile.html",
        "hr_external/templates/hr_external/industry_home.html",
        "hr_external/templates/hr_external/industry_engagement_detail.html",
        "hr_external/templates/hr_external/hiring_list.html",
        "hr_external/templates/hr_external/hiring_detail.html",
        "hr_external/templates/hr_external/tasks_home.html",
        "hr_external/templates/hr_external/renewals_home.html",
        "hr_external/templates/hr_external/exits_home.html",
    )

    def test_runtime_templates_use_canonical_shell_and_compile(self):
        for relative_path in self.RUNTIME_TEMPLATES:
            with self.subTest(template=relative_path):
                template_path = Path(settings.BASE_DIR) / relative_path
                source = template_path.read_text(encoding="utf-8")
                self.assertTrue(
                    source.lstrip().startswith(
                        '{% extends "hr_external/workspace_base.html" %}'
                    ),
                    f"{relative_path} must extend the shared HR08 V2 workspace shell",
                )
                self.assertNotIn('{% extends "base.html" %}', source)
                self.assertNotIn('href="#"', source)
                self.assertNotIn(" UUID", source)
                self.assertNotIn("组织 ID", source)
                self.assertNotIn('style="', source)
                engines["django"].engine.from_string(source)

    def test_workspace_shell_loads_canonical_v2_assets(self):
        shell_path = (
            Path(settings.BASE_DIR)
            / "hr_external/templates/hr_external/workspace_base.html"
        )
        source = shell_path.read_text(encoding="utf-8")
        self.assertTrue(source.lstrip().startswith('{% extends "index.html" %}'))
        for asset in (
            "hr/css/hr-tokens.css",
            "hr/css/hr-components.css",
            "hr/css/hr-v2.css",
            "hr/css/hr08-workspace.css",
            "hr/js/pages/hr08-workspace.js",
        ):
            self.assertIn(asset, source)

    def test_runtime_has_no_duplicate_theme_overrides(self):
        theme_root = Path(settings.BASE_DIR) / "horilla_theme/templates/hr_external"
        duplicate_names = {
            "hiring_detail.html",
            "tasks_home.html",
            "renewals_home.html",
            "exits_home.html",
        }
        self.assertFalse(duplicate_names & {path.name for path in theme_root.glob("*.html")})

    def test_workspace_javascript_uses_canonical_safe_pickers(self):
        source = (
            Path(settings.FRONTEND_DIR) / "static/hr/js/pages/hr08-workspace.js"
        ).read_text(encoding="utf-8")
        self.assertIn("/api/v1/hr/external-teachers", source)
        self.assertIn("/api/v1/hr/structure/organizations/bootstrap", source)
        self.assertNotIn("/api/hr/v1/", source)
        self.assertNotIn("UUID", source)
        self.assertNotIn("clearanceItems\" placeholder", source)
