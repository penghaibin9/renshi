from pathlib import Path

from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase


class RecruitmentUiTemplateContractTests(SimpleTestCase):
    TEMPLATE_PATHS = (
        ("campaigns", "console.html"),
        ("plans", "plans.html"),
        ("candidates", "candidates.html"),
        ("qualification", "qualification.html"),
        ("assessment", "assessment.html"),
        ("proposed_hires", "proposed.html"),
    )

    def test_all_recruitment_workspace_templates_compile(self):
        """Keep Django's extends-first contract covered before browser CI."""
        for directory, filename in self.TEMPLATE_PATHS:
            with self.subTest(template=f"{directory}/{filename}"):
                template_path = (
                    Path(settings.FRONTEND_DIR)
                    / "templates"
                    / "hr"
                    / "recruitment"
                    / directory
                    / filename
                )
                source = template_path.read_text(encoding="utf-8")

                # Compilation catches an extends tag placed after any other
                # template tag without rendering or requiring database loaders.
                engines["django"].engine.from_string(source)
