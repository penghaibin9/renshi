"""Regression contracts for the public-facing legacy-brand retirement."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class PublicBrandRetirementContractTests(SimpleTestCase):
    def test_public_defaults_use_the_university_platform_brand(self):
        context_source = (
            Path(settings.BASE_DIR) / "base" / "context_processors.py"
        ).read_text(encoding="utf-8")
        manifest_source = (
            Path(settings.FRONTEND_DIR) / "static" / "build" / "manifest.json"
        ).read_text(encoding="utf-8")

        self.assertNotIn('"white_label_company_name": "Horilla"', context_source)
        self.assertIn("高校人事一体化平台", context_source)
        self.assertNotIn("Horilla", manifest_source)
        self.assertIn("高校人事一体化平台", manifest_source)

    def test_retired_logo_files_cannot_reappear_as_defaults(self):
        frontend = Path(settings.FRONTEND_DIR)
        backend = Path(settings.BASE_DIR)
        retired_assets = (
            frontend / "static" / "images" / "ui" / "auth-logo.png",
            frontend / "static" / "images" / "ui" / "horilla-logo.png",
            frontend / "static" / "images" / "ui" / "horilla-sticker-round.png",
            backend
            / "horilla_theme"
            / "static"
            / "horilla_theme"
            / "assets"
            / "img"
            / "horilla-logo.png",
        )
        for asset in retired_assets:
            with self.subTest(asset=str(asset)):
                self.assertFalse(asset.exists())

        replacement = frontend / "static" / "images" / "ui" / "university-seal.jpg"
        self.assertTrue(replacement.exists())
        self.assertGreater(replacement.stat().st_size, 0)
