import re
from pathlib import Path

from django.test import SimpleTestCase


class ProductionContainerHardeningContractTests(SimpleTestCase):
    APP_SERVICES = (
        "release",
        "web",
        "hr18-submission-worker",
        "hr18-exchange-worker",
        "legacy-scheduler",
        "employee-scheduler",
        "backup-scheduler",
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = Path(__file__).resolve().parents[2]
        cls.compose = (root / "docker-compose.prod.yml").read_text(
            encoding="utf-8"
        )

    def _service_body(self, service):
        match = re.search(
            rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
            self.compose,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match, f"missing production service {service}")
        return match.group("body")

    def test_hardening_anchor_is_fail_closed(self):
        self.assertIn("x-app-hardening: &app-hardening", self.compose)
        self.assertIn("read_only: true", self.compose)
        self.assertIn("/tmp:rw,noexec,nosuid,size=256m", self.compose)
        self.assertIn("no-new-privileges:true", self.compose)
        self.assertIn("cap_drop:\n    - ALL", self.compose)

    def test_every_application_service_uses_hardening_anchor(self):
        for service in self.APP_SERVICES:
            with self.subTest(service=service):
                self.assertIn("<<: *app-hardening", self._service_body(service))

    def test_redis_runs_as_non_root_without_capabilities(self):
        redis = self._service_body("redis")
        self.assertIn("user: redis", redis)
        self.assertIn("read_only: true", redis)
        self.assertIn("no-new-privileges:true", redis)
        self.assertIn("cap_drop:\n      - ALL", redis)

    def test_clamav_is_private_persistent_and_gates_web_readiness(self):
        clamav = self._service_body("clamav")
        web = self._service_body("web")
        self.assertIn("image: clamav/clamav:stable@sha256:", clamav)
        self.assertIn("CLAMD_CONF_StreamMaxLength: 50M", clamav)
        self.assertIn('expose:\n      - "3310"', clamav)
        self.assertNotIn("ports:", clamav)
        self.assertIn("clamav_data:/var/lib/clamav", clamav)
        self.assertIn("/usr/local/bin/clamdcheck.sh", clamav)
        self.assertIn("clamav:\n        condition: service_healthy", web)
