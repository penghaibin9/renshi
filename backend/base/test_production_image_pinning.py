import re
from pathlib import Path

from django.test import SimpleTestCase


class ProductionImagePinningContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = Path(__file__).resolve().parents[2]
        cls.dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        cls.compose = (root / "docker-compose.prod.yml").read_text(
            encoding="utf-8"
        )
        cls.dependabot = (root / ".github/dependabot.yml").read_text(
            encoding="utf-8"
        )

    def test_every_python_build_stage_uses_an_immutable_digest(self):
        python_stages = re.findall(r"^FROM python:[^\s]+", self.dockerfile, re.MULTILINE)
        self.assertEqual(len(python_stages), 2)
        for stage in python_stages:
            self.assertRegex(stage, r"@sha256:[0-9a-f]{64}$")

    def test_production_data_plane_images_use_immutable_digests(self):
        for image in ("mysql:8.4", "redis:7-alpine", "clamav/clamav:stable", "nginx:alpine"):
            with self.subTest(image=image):
                self.assertRegex(
                    self.compose,
                    rf"image: {re.escape(image)}@sha256:[0-9a-f]{{64}}",
                )

    def test_dependabot_tracks_docker_digest_updates(self):
        self.assertIn("package-ecosystem: docker", self.dependabot)
