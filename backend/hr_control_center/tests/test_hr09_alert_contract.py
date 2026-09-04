from pathlib import Path

from django.test import SimpleTestCase


class Hr09AlertContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(__file__).resolve().parents[1] / "services" / "alert_service.py"
        ).read_text(encoding="utf-8")

    def test_certificate_expiry_rule_is_enabled_and_registered(self):
        self.assertIn('"hr09.certificate_expiry": {', self.source)
        self.assertIn('"authority_source": True', self.source)
        self.assertIn(
            '"hr09.certificate_expiry": _rule_hr09_certificate_expiry',
            self.source,
        )

    def test_certificate_expiry_uses_tenant_scoped_authoritative_facts(self):
        section = self.source[
            self.source.index("def _rule_hr09_certificate_expiry"):
            self.source.index("ALERT_RULES =")
        ]
        self.assertIn("tenant_id=context.tenant_id", section)
        self.assertIn("HrPersonCredential.objects.filter", section)
        self.assertIn("CredentialStatus.ACTIVE", section)
        self.assertIn("CredentialStatus.EXPIRED", section)
        self.assertIn("DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT", section)

    def test_authority_mode_keeps_authoritative_alert_rules(self):
        self.assertIn(
            'authority_mode == AUTHORITY_ONLY and not config.get("authority_source")',
            self.source,
        )

    def test_every_enabled_alert_rule_must_have_an_executor(self):
        self.assertIn(
            'cfg.get("enabled", True) and key not in ALERT_RULES',
            self.source,
        )
        self.assertIn("已启用的预警规则缺少执行器", self.source)
