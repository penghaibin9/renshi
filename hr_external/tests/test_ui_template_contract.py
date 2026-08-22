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
        "horilla_theme/templates/hr_external/hiring_detail.html",
        "horilla_theme/templates/hr_external/tasks_home.html",
        "horilla_theme/templates/hr_external/renewals_home.html",
        "horilla_theme/templates/hr_external/exits_home.html",
    )

    def test_runtime_templates_use_canonical_shell_and_compile(self):
        for relative_path in self.RUNTIME_TEMPLATES:
            with self.subTest(template=relative_path):
                template_path = Path(settings.BASE_DIR) / relative_path
                source = template_path.read_text(encoding="utf-8")
                self.assertTrue(
                    source.lstrip().startswith('{% extends "index.html" %}'),
                    f"{relative_path} must extend index.html, not a retired template shell",
                )
                self.assertNotIn('{% extends "base.html" %}', source)
                engines["django"].engine.from_string(source)
