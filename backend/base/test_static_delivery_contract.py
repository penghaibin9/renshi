from pathlib import Path

from django.test import SimpleTestCase


class StaticDeliveryContractTests(SimpleTestCase):
    def test_unversioned_static_assets_are_not_cached_as_immutable(self):
        root = Path(__file__).resolve().parents[2]
        settings = (root / "backend/horilla/settings/base.py").read_text(
            encoding="utf-8"
        )
        nginx = (root / "deploy/docker/nginx.conf").read_text(encoding="utf-8")

        self.assertIn(
            'STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"',
            settings,
        )
        self.assertIn("location /static/", nginx)
        self.assertIn("expires 1h;", nginx)
        self.assertNotIn('Cache-Control "public, immutable"', nginx)
