from pathlib import Path

from django.test import SimpleTestCase


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
THEME_ROOT = REPOSITORY_ROOT / "backend" / "horilla_theme"


class TailwindProductionContractTests(SimpleTestCase):
    def test_templates_do_not_load_browser_compilers(self):
        forbidden = (
            "tailwindcdn.js",
            "assets/js/tailwind.js",
            "window.tailwind.config",
            "cdn.tailwindcss.com",
        )
        for template in (THEME_ROOT / "templates").rglob("*.html"):
            source = template.read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, source, f"{template} still contains {marker}")

    def test_compiled_styles_cover_application_palettes(self):
        stylesheet = (
            THEME_ROOT / "static" / "horilla_theme" / "assets" / "css" / "tailwind.css"
        ).read_text(encoding="utf-8")
        for selector in (
            ".bg-primary-600{",
            ".bg-brand-600{",
            ".bg-info-600{",
            ".hover\\:bg-brand-800:hover{",
            ".focus-visible\\:border-primary-700:focus-visible{",
        ):
            self.assertIn(selector, stylesheet)
        self.assertNotIn("cdn.tailwindcss.com should not be used in production", stylesheet)

    def test_tailwind_build_is_version_pinned(self):
        package = (REPOSITORY_ROOT / "package.json").read_text(encoding="utf-8")
        config = (REPOSITORY_ROOT / "tailwind.config.cjs").read_text(encoding="utf-8")
        self.assertIn('"tailwindcss": "3.4.19"', package)
        self.assertIn('"build:css"', package)
        self.assertIn("--color-${name}", config)
        self.assertIn('themedScale("primary"', config)

    def test_core_hr_ui_does_not_depend_on_third_party_assets(self):
        ui_roots = (
            REPOSITORY_ROOT / "frontend" / "templates" / "hr",
            REPOSITORY_ROOT / "frontend" / "static" / "hr",
        )
        forbidden = ("http://", "https://", "//cdn", "ui-avatars.com")
        extensions = {".css", ".html", ".js"}

        for root in ui_roots:
            for asset in root.rglob("*"):
                if asset.suffix not in extensions or "vendor" in asset.parts:
                    continue
                source = asset.read_text(encoding="utf-8")
                for marker in forbidden:
                    self.assertNotIn(
                        marker,
                        source,
                        f"{asset} depends on external asset marker {marker}",
                    )
