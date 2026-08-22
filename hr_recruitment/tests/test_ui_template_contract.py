from pathlib import Path

from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase


class RecruitmentUiTemplateContractTests(SimpleTestCase):
    def test_campaign_console_template_compiles(self):
        """Keep Django's required extends-first contract covered before browser CI."""
        template_path = (
            Path(settings.BASE_DIR)
            / "templates"
            / "hr"
            / "recruitment"
            / "campaigns"
            / "console.html"
        )
        source = template_path.read_text(encoding="utf-8")

        # Compilation is enough to catch an extends tag placed after another
        # template tag, without rendering or requiring database-backed loaders.
        engines["django"].engine.from_string(source)
