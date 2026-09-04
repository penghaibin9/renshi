from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from base.email_logging import (
    record_email_log,
    resolve_email_log_company,
    sanitize_email_log_body,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class EmailLogSecurityTests(SimpleTestCase):
    def test_business_mail_html_is_sanitized(self):
        body = sanitize_email_log_body(
            "会议通知",
            '<p onclick="steal()">正文</p><script>alert(1)</script>'
            '<a href="javascript:alert(2)">链接</a>',
        )

        self.assertIn("<p>正文</p>", body)
        self.assertNotIn("onclick", body)
        self.assertNotIn("<script", body)
        self.assertNotIn("javascript:", body)

    def test_authentication_mail_body_is_redacted(self):
        body = sanitize_email_log_body(
            "重置密码验证码", "您的验证码是 123456，token=top-secret"
        )

        self.assertIn("认证类邮件正文不写入系统日志", body)
        self.assertNotIn("123456", body)
        self.assertNotIn("top-secret", body)

    def test_company_resolution_prefers_concrete_request_scope(self):
        selected = SimpleNamespace(pk=8)
        request = SimpleNamespace(selected_company_instance=selected)

        self.assertIs(resolve_email_log_company(request), selected)

    @patch("base.models.EmailLog.objects.create")
    def test_audit_log_normalizes_one_row_per_recipient(self, create):
        record_email_log(
            subject="录用通知",
            body="<p>欢迎入职</p>",
            from_email="人事处 <hr@example.edu.cn>",
            to=["张老师 <zhang@example.edu.cn>", "li@example.edu.cn"],
            status="sent",
            company=17,
        )

        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].kwargs["to"], "zhang@example.edu.cn")
        self.assertEqual(create.call_args_list[0].kwargs["from_email"], "hr@example.edu.cn")
        self.assertEqual(create.call_args_list[0].kwargs["company_id_id"], 17)

    def test_mail_templates_use_scriptless_iframe(self):
        templates = (
            BACKEND_ROOT / "employee/templates/tabs/mail_log.html",
            BACKEND_ROOT / "recruitment/templates/candidate/mail_log.html",
            BACKEND_ROOT / "base/templates/cbv/mail_log_tab/iframe.html",
        )
        for template in templates:
            source = template.read_text(encoding="utf-8")
            self.assertNotIn("log.body|safe", source, template)
            self.assertNotIn("document.write", source, template)
            self.assertIn("sandbox", source, template)
            self.assertIn("srcdoc", source, template)
            self.assertIn("safe_email_log_body", source, template)

    def test_mail_backends_do_not_persist_raw_bodies_directly(self):
        backends = (
            BACKEND_ROOT / "base/backends.py",
            BACKEND_ROOT / "outlook_auth/backends.py",
            BACKEND_ROOT / "horilla/backends.py",
        )
        for backend in backends:
            source = backend.read_text(encoding="utf-8")
            self.assertNotIn("EmailLog(", source, backend)
            self.assertIn("record_email_log(", source, backend)

    def test_all_mail_log_queries_include_tenant_scope(self):
        sources = (
            BACKEND_ROOT / "base/cbv/mail_log_tab.py",
            BACKEND_ROOT / "recruitment/cbv/candidate_mail_log.py",
            BACKEND_ROOT / "employee/models.py",
            BACKEND_ROOT / "recruitment/models.py",
            BACKEND_ROOT / "employee/views.py",
            BACKEND_ROOT / "recruitment/views/views.py",
        )
        for source_path in sources:
            source = source_path.read_text(encoding="utf-8")
            self.assertNotIn("EmailLog.objects.filter(to__icontains", source, source_path)

    def test_email_audit_model_and_admin_are_append_only(self):
        model_source = (BACKEND_ROOT / "base/models.py").read_text(encoding="utf-8")
        admin_source = (BACKEND_ROOT / "base/admin.py").read_text(encoding="utf-8")

        self.assertIn("class EmailLogQuerySet", model_source)
        self.assertIn("Company, on_delete=models.PROTECT", model_source)
        self.assertIn("class EmailLogAdmin", admin_source)
        self.assertIn("def has_delete_permission", admin_source)
