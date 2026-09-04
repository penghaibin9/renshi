import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from hr_recruitment.public.views import (
    PUBLIC_APPLY_IDENTITY_LIMIT,
    PublicPortalError,
    _issue_receipt_recovery_challenge,
    _json_object,
    _rate_limited,
    _read_candidate_receipt,
    _verify_receipt_recovery_challenge,
)


class PublicRecruitmentRequestGuardTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_rejects_non_json_posts(self):
        request = self.factory.post("/recruit/token/apply", data={"name": "张三"})
        with self.assertRaises(PublicPortalError) as caught:
            _json_object(request)
        self.assertEqual(caught.exception.status, 415)

    def test_rejects_oversized_json_before_parsing(self):
        request = self.factory.post(
            "/recruit/token/apply",
            data=b'{' + b'"x":"' + (b'a' * (65 * 1024)) + b'"}',
            content_type="application/json",
        )
        with self.assertRaises(PublicPortalError) as caught:
            _json_object(request)
        self.assertEqual(caught.exception.status, 413)

    @override_settings(FAIL2BAN_TRUST_X_REAL_IP=False)
    def test_identity_limit_does_not_block_other_applicants_on_same_ip(self):
        request = self.factory.post(
            "/recruit/token/apply",
            data=json.dumps({}),
            content_type="application/json",
            REMOTE_ADDR="10.0.0.8",
        )
        for _ in range(PUBLIC_APPLY_IDENTITY_LIMIT):
            self.assertFalse(
                _rate_limited(
                    request,
                    scope="apply-test",
                    identity="tenant|a@example.edu.cn|13800138000",
                    identity_limit=PUBLIC_APPLY_IDENTITY_LIMIT,
                )
            )
        self.assertTrue(
            _rate_limited(
                request,
                scope="apply-test",
                identity="tenant|a@example.edu.cn|13800138000",
                identity_limit=PUBLIC_APPLY_IDENTITY_LIMIT,
            )
        )
        self.assertFalse(
            _rate_limited(
                request,
                scope="apply-test",
                identity="tenant|b@example.edu.cn|13900139000",
                identity_limit=PUBLIC_APPLY_IDENTITY_LIMIT,
            )
        )

    def test_receipt_recovery_emails_otp_and_returns_tenant_bound_receipt(self):
        request = self.factory.post(
            "/recruit/token/receipt/request",
            data=json.dumps({}),
            content_type="application/json",
            REMOTE_ADDR="10.0.0.9",
        )
        campaign = SimpleNamespace(tenant_id=8, title="教师招聘")
        candidate = SimpleNamespace(
            tenant_id=8,
            candidate_uid="candidate-uid-8",
            primary_email="teacher@example.edu.cn",
        )
        queryset = SimpleNamespace(first=lambda: candidate)
        with (
            patch(
                "hr_recruitment.models.HrRecruitmentCandidate.objects.filter",
                return_value=queryset,
            ),
            patch("hr_recruitment.public.views.secrets.randbelow", return_value=123456),
            patch(
                "hr_recruitment.public.views.send_deployment_email", return_value=1
            ) as send,
        ):
            challenge_id = _issue_receipt_recovery_challenge(
                request,
                campaign,
                email="teacher@example.edu.cn",
                mobile="13800138000",
            )
            token = _verify_receipt_recovery_challenge(
                campaign,
                challenge_id=challenge_id,
                otp="123456",
            )

        self.assertIn("123456", send.call_args.kwargs["body"])
        self.assertEqual(send.call_args.kwargs["to"], ["teacher@example.edu.cn"])
        self.assertEqual(
            _read_candidate_receipt(token),
            {"candidate_uid": "candidate-uid-8", "tenant_id": 8},
        )

    def test_unknown_recovery_identity_does_not_send_email_or_issue_receipt(self):
        request = self.factory.post(
            "/recruit/token/receipt/request",
            data=json.dumps({}),
            content_type="application/json",
            REMOTE_ADDR="10.0.0.10",
        )
        campaign = SimpleNamespace(tenant_id=9, title="辅导员招聘")
        queryset = SimpleNamespace(first=lambda: None)
        with (
            patch(
                "hr_recruitment.models.HrRecruitmentCandidate.objects.filter",
                return_value=queryset,
            ),
            patch("hr_recruitment.public.views.secrets.randbelow", return_value=654321),
            patch("hr_recruitment.public.views.send_deployment_email") as send,
        ):
            challenge_id = _issue_receipt_recovery_challenge(
                request,
                campaign,
                email="unknown@example.edu.cn",
                mobile="13900139000",
            )
        send.assert_not_called()
        with self.assertRaises(PublicPortalError):
            _verify_receipt_recovery_challenge(
                campaign,
                challenge_id=challenge_id,
                otp="654321",
            )
