from pathlib import Path

from django.test import SimpleTestCase


class PublicRecruitmentReceiptContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = (
            Path(__file__).resolve().parents[1] / "public" / "views.py"
        ).read_text(encoding="utf-8")

    def test_receipt_is_signed_limited_and_tenant_bound(self):
        self.assertIn("def _issue_candidate_receipt", self.source)
        self.assertIn("def _read_candidate_receipt", self.source)
        self.assertIn('"candidate_uid": candidate.candidate_uid', self.source)
        self.assertIn('"tenant_id": int(candidate.tenant_id)', self.source)
        self.assertIn("max_age=getattr(", self.source)
        self.assertIn("except signing.SignatureExpired", self.source)
        self.assertIn("except signing.BadSignature", self.source)

    def test_application_query_requires_receipt_and_two_contact_factors(self):
        section = self.source[self.source.index("def public_my_applications"):]
        self.assertIn("not primary_email or not primary_mobile or not access_token", section)
        self.assertIn('tenant_id=receipt["tenant_id"]', section)
        self.assertIn('candidate_uid=receipt["candidate_uid"]', section)
        self.assertIn("primary_email__iexact=primary_email", section)
        self.assertIn("primary_mobile=primary_mobile", section)
        self.assertIn('"canonical_status": a.canonical_status', section)
        self.assertIn('"canonical_status_label": status_label(', section)
        self.assertIn("APPLICATION_STATUS_LABELS, a.canonical_status", section)

    def test_apply_responses_return_receipt(self):
        section = self.source[
            self.source.index("def public_apply"):
            self.source.index("def public_my_applications")
        ]
        self.assertGreaterEqual(
            section.count('"access_token": _issue_candidate_receipt(candidate)'),
            3,
        )

    def test_public_apply_enforces_campaign_state_and_window(self):
        section = self.source[
            self.source.index("def public_apply"):
            self.source.index("def public_my_applications")
        ]
        self.assertIn("campaign.status != CampaignStatus.OPEN", section)
        self.assertIn("now < campaign.application_open_at", section)
        self.assertIn("now > campaign.application_close_at", section)

    def test_public_listing_hides_draft_and_cancelled_positions(self):
        self.assertGreaterEqual(
            self.source.count('exclude(status__in=["DRAFT", "CANCELLED"])'),
            2,
        )

    def test_public_apply_requires_and_records_consent_retention(self):
        section = self.source[
            self.source.index("def public_apply"):
            self.source.index("def public_my_applications")
        ]
        self.assertIn('body.get("privacy_consent") is not True', section)
        self.assertIn("candidate_service.record_consent(", section)
        self.assertIn("HR04_PRIVACY_NOTICE_VERSION", section)
        self.assertIn("HR04_CANDIDATE_RETENTION_DAYS", section)
        self.assertIn("CandidateServiceError", self.source)

    def test_public_campaign_template_exists_and_supports_apply_query(self):
        app_template = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "hr"
            / "recruitment"
            / "portal"
            / "campaign.html"
        ).read_text(encoding="utf-8")
        frontend_template = (
            Path(__file__).resolve().parents[3]
            / "frontend"
            / "templates"
            / "hr"
            / "recruitment"
            / "portal"
            / "campaign.html"
        ).read_text(encoding="utf-8")
        for template in (app_template, frontend_template):
            self.assertIn("privacy_consent", template)
            self.assertIn("招聘个人信息处理告知（报名之前请阅读）", template)
            self.assertIn("privacy_school_name", template)
            self.assertIn("privacy_retention_days", template)
            self.assertIn("privacy_contact", template)
            self.assertIn("privacy_notice_version", template)
            self.assertIn("查阅、复制、更正、补充、删除、限制处理或撤回同意", template)
            self.assertIn("canonical_status_label || item.canonical_status", template)
            self.assertIn("localStorage.setItem(receiptKey", template)
            self.assertIn("/receipt/request", template)
            self.assertIn("/receipt/verify", template)
        self.assertIn('id="apply-form"', app_template)
        self.assertIn('id="query-form"', app_template)
        self.assertIn('id="receipt-request-form"', app_template)
        self.assertIn('id="receipt-verify-form"', app_template)
        self.assertIn('id="portal-apply-form"', frontend_template)
        self.assertIn('id="portal-query-form"', frontend_template)
        self.assertIn('id="portal-receipt-request-form"', frontend_template)
        self.assertIn('id="portal-receipt-verify-form"', frontend_template)

    def test_public_campaign_supplies_server_owned_privacy_notice(self):
        section = self.source[
            self.source.index("def _privacy_notice_context"):
            self.source.index("def public_position")
        ]
        self.assertIn("Company.objects.filter(pk=campaign.tenant_id)", section)
        self.assertIn("HR04_PRIVACY_NOTICE_VERSION", section)
        self.assertIn("HR04_CANDIDATE_RETENTION_DAYS", section)
        self.assertIn("HR04_PRIVACY_CONTACT", section)
        self.assertIn("context.update(_privacy_notice_context(campaign))", section)

    def test_public_posts_are_json_bounded_and_shared_cache_rate_limited(self):
        self.assertIn('request.content_type != "application/json"', self.source)
        self.assertIn("PUBLIC_JSON_MAX_BYTES = 64 * 1024", self.source)
        self.assertIn("PUBLIC_SHARED_IP_LIMIT", self.source)
        self.assertIn("PUBLIC_APPLY_IDENTITY_LIMIT", self.source)
        self.assertIn("PUBLIC_RECEIPT_QUERY_LIMIT", self.source)
        self.assertIn("cache.add(", self.source)
        self.assertIn("cache.incr(", self.source)

    def test_receipt_recovery_is_tenant_bound_otp_and_email_only(self):
        self.assertIn("def public_request_receipt_recovery", self.source)
        self.assertIn("def public_verify_receipt_recovery", self.source)
        self.assertIn("tenant_id=campaign.tenant_id", self.source)
        self.assertIn("PUBLIC_RECEIPT_OTP_TTL_SECONDS = 300", self.source)
        self.assertIn("PUBLIC_RECEIPT_OTP_MAX_ATTEMPTS = 5", self.source)
        self.assertIn("send_deployment_email(", self.source)
        self.assertIn("constant_time_compare(", self.source)
