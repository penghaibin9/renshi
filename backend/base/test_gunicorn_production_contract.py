import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


class GunicornProductionContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(__file__).resolve().parents[2]

    def test_production_preload_and_post_fork_connection_cleanup_are_enabled(self):
        compose = (self.root / "docker-compose.prod.yml").read_text(encoding="utf-8")
        development_compose = (self.root / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        config = (self.root / "deploy/docker/gunicorn.conf.py").read_text(encoding="utf-8")
        self.assertIn('GUNICORN_PRELOAD: "true"', compose)
        self.assertIn("GUNICORN_WORKERS: ${GUNICORN_WORKERS:-3}", compose)
        self.assertIn('os.environ.get("GUNICORN_PRELOAD"', config)
        self.assertIn('os.environ.get("GUNICORN_WORKERS", "").strip()', config)
        self.assertIn("if not 1 <= workers <= 32", config)
        self.assertIn("def post_fork", config)
        self.assertIn("django_settings.configured", config)
        self.assertIn("connections.close_all()", config)
        self.assertIn("control_socket_disable = True", config)
        self.assertIn('GUNICORN_WORKERS: "${GUNICORN_WORKERS:-3}"', development_compose)
        self.assertIn("start_period: 240s", development_compose)

    def test_empty_worker_environment_value_uses_safe_automatic_default(self):
        with patch.dict(os.environ, {"GUNICORN_WORKERS": ""}):
            config = runpy.run_path(
                str(self.root / "deploy/docker/gunicorn.conf.py")
            )
        self.assertGreaterEqual(config["workers"], 2)
        self.assertLessEqual(config["workers"], 8)

    def test_out_of_range_worker_count_fails_fast(self):
        with patch.dict(os.environ, {"GUNICORN_WORKERS": "64"}):
            with self.assertRaisesMessage(ValueError, "between 1 and 32"):
                runpy.run_path(str(self.root / "deploy/docker/gunicorn.conf.py"))
