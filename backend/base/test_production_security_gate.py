import base64

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from horilla.settings.security import (
    validate_hr04_privacy_configuration,
    validate_internal_service_credentials,
    validate_malware_scanner_configuration,
    validate_field_encryption_configuration,
    validate_mfa_email_configuration,
    validate_login_security_configuration,
    validate_production_secrets,
    validate_required_external_integrations,
)


class Hr04PrivacyConfigurationGateTests(SimpleTestCase):
    valid = {
        "notice_version": "2026-01",
        "retention_days": 730,
        "privacy_contact": "人事处 010-12345678 hr@university.cn",
        "material_max_bytes": 20 * 1024 * 1024,
        "scan_max_bytes": 50 * 1024 * 1024,
    }

    def test_real_school_privacy_configuration_passes(self):
        validate_hr04_privacy_configuration(**self.valid)

    def test_placeholder_contact_is_rejected(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "HR04_PRIVACY_CONTACT"):
            validate_hr04_privacy_configuration(
                **{**self.valid, "privacy_contact": "招聘公告公布的联系方式"}
            )

    def test_material_limit_cannot_exceed_scanner_limit(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "HR04_APPLICATION_MATERIAL_MAX_BYTES"
        ):
            validate_hr04_privacy_configuration(
                **{
                    **self.valid,
                    "material_max_bytes": 51 * 1024 * 1024,
                }
            )


class LoginSecurityConfigurationGateTests(SimpleTestCase):
    valid = {
        "max_attempts": 5,
        "ip_max_attempts": 100,
        "attempt_window": 900,
        "ban_time": 900,
        "remember_seconds": 14 * 24 * 60 * 60,
    }

    def test_shared_campus_network_defaults_pass(self):
        validate_login_security_configuration(**self.valid)

    def test_ip_threshold_cannot_be_lower_than_account_threshold(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "IP_MAX_RETRY"):
            validate_login_security_configuration(
                **{**self.valid, "max_attempts": 20, "ip_max_attempts": 19}
            )

    def test_remember_me_cannot_exceed_thirty_days(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "REMEMBER_ME"):
            validate_login_security_configuration(
                **{**self.valid, "remember_seconds": 31 * 24 * 60 * 60}
            )


class ProductionFieldEncryptionGateTests(SimpleTestCase):
    valid_key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    previous_key = base64.urlsafe_b64encode(b"p" * 32).decode("ascii")

    def test_valid_rotation_keyring_passes(self):
        validate_field_encryption_configuration(
            f"current:{self.valid_key},previous:{self.previous_key}", production=True
        )

    def test_missing_keyring_fails_closed(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "is required"):
            validate_field_encryption_configuration("", production=True)

    def test_invalid_key_material_fails_closed(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "must be a Fernet key"):
            validate_field_encryption_configuration(
                "primary:not-a-fernet-key", production=True
            )

    def test_duplicate_key_ids_fail_closed(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "repeats key id"):
            validate_field_encryption_configuration(
                f"same:{self.valid_key},same:{self.valid_key}", production=True
            )


class InternalServiceCredentialGateTests(SimpleTestCase):
    valid = {
        "HR09": "hr09-internal-token-with-more-than-32-bytes",
        "HR11": "hr11-internal-token-with-more-than-32-bytes",
    }

    def test_distinct_strong_credentials_pass(self):
        validate_internal_service_credentials(self.valid, ("HR09", "HR11"))

    def test_missing_or_placeholder_credentials_fail_closed(self):
        for configured in (
            {},
            {**self.valid, "HR09": ""},
            {**self.valid, "HR11": "change-me-service-token"},
        ):
            with self.subTest(configured=configured):
                with self.assertRaisesMessage(
                    ImproperlyConfigured, "internal service credential"
                ):
                    validate_internal_service_credentials(
                        configured, ("HR09", "HR11")
                    )

    def test_callers_cannot_share_one_credential(self):
        shared = "shared-internal-token-with-more-than-32-bytes"
        with self.assertRaisesMessage(ImproperlyConfigured, "must be distinct"):
            validate_internal_service_credentials(
                {"HR09": shared, "HR11": shared}, ("HR09", "HR11")
            )


class ProductionMfaEmailGateTests(SimpleTestCase):
    valid = {
        "enabled": True,
        "email_host": "smtp.university.edu",
        "email_port": 587,
        "email_host_user": "hr-system@university.edu",
        "email_host_password": "production-smtp-credential",
        "from_email": "noreply@university.edu",
        "use_tls": True,
        "use_ssl": False,
        "fail_silently": False,
        "timeout": 10,
        "otp_ttl": 300,
        "max_attempts": 5,
        "resend_cooldown": 60,
        "production": True,
    }

    def test_complete_production_mfa_configuration_passes(self):
        validate_mfa_email_configuration(**self.valid)

    def test_production_cannot_disable_mfa(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "must be enabled"):
            validate_mfa_email_configuration(**{**self.valid, "enabled": False})

    def test_example_smtp_host_is_rejected(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "real production SMTP"):
            validate_mfa_email_configuration(
                **{**self.valid, "email_host": "smtp.example.edu.cn"}
            )

    def test_transport_encryption_is_unambiguous(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "Exactly one"):
            validate_mfa_email_configuration(
                **{**self.valid, "use_tls": True, "use_ssl": True}
            )
        with self.assertRaisesMessage(ImproperlyConfigured, "Exactly one"):
            validate_mfa_email_configuration(
                **{**self.valid, "use_tls": False, "use_ssl": False}
            )

    def test_silent_delivery_failure_is_rejected(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "must be False"):
            validate_mfa_email_configuration(
                **{**self.valid, "fail_silently": True}
            )

    def test_smtp_account_and_credential_are_required(self):
        for key, value, message in (
            ("email_host_user", "replace-with-smtp-account", "EMAIL_HOST_USER"),
            ("email_host_password", "change-me-smtp-password", "EMAIL_HOST_PASSWORD"),
            ("email_host_password", "", "EMAIL_HOST_PASSWORD"),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaisesMessage(ImproperlyConfigured, message):
                    validate_mfa_email_configuration(
                        **{**self.valid, key: value}
                    )

    def test_otp_security_bounds_are_enforced(self):
        for key, value, message in (
            ("otp_ttl", 30, "MFA_OTP_TTL_SECONDS"),
            ("max_attempts", 20, "MFA_OTP_MAX_ATTEMPTS"),
            ("resend_cooldown", 5, "MFA_OTP_RESEND_COOLDOWN_SECONDS"),
        ):
            with self.subTest(key=key):
                with self.assertRaisesMessage(ImproperlyConfigured, message):
                    validate_mfa_email_configuration(
                        **{**self.valid, key: value}
                    )


class MalwareScannerConfigurationGateTests(SimpleTestCase):
    valid = {
        "required": True,
        "host": "clamav",
        "port": 3310,
        "timeout_seconds": 10,
        "max_bytes": 50 * 1024 * 1024,
        "production": True,
    }

    def test_complete_production_scanner_configuration_passes(self):
        validate_malware_scanner_configuration(**self.valid)

    def test_production_cannot_disable_scanning(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "must be enabled"):
            validate_malware_scanner_configuration(
                **{**self.valid, "required": False}
            )

    def test_required_scanner_needs_private_host(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "HOST is required"):
            validate_malware_scanner_configuration(**{**self.valid, "host": ""})

    def test_scan_limit_cannot_exceed_ingress_limit(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "50 MiB"):
            validate_malware_scanner_configuration(
                **{**self.valid, "max_bytes": 50 * 1024 * 1024 + 1}
            )


class ProductionSecurityGateTests(SimpleTestCase):
    valid = {
        "secret_key": "Prod-2026!University-HR#Secret$Key%With&Diverse*Characters+64",
        "allowed_hosts": ["hr.example.edu.cn"],
        "db_init_password": "database-bootstrap-secret-value",
        "csrf_trusted_origins": ["https://hr.example.edu.cn"],
        "database_password": "database-application-secret",
        "redis_url": "redis://:redis-runtime-secret@redis:6379/0",
        "redis_password": "redis-runtime-secret",
        "backup_encryption_key": "backup-encryption-secret-at-least-32-bytes",
    }

    def test_complete_secure_configuration_passes(self):
        validate_production_secrets(**self.valid)

    def test_http_csrf_origin_fails_closed(self):
        values = {**self.valid, "csrf_trusted_origins": ["http://hr.example.edu.cn"]}
        with self.assertRaisesMessage(ImproperlyConfigured, "invalid production origin"):
            validate_production_secrets(**values)

    def test_redis_password_mismatch_fails_closed(self):
        values = {**self.valid, "redis_password": "different-secret"}
        with self.assertRaisesMessage(ImproperlyConfigured, "must match"):
            validate_production_secrets(**values)

    def test_placeholder_database_password_fails_closed(self):
        values = {**self.valid, "database_password": "change-me"}
        with self.assertRaisesMessage(ImproperlyConfigured, "database password"):
            validate_production_secrets(**values)

    def test_csrf_host_must_be_allowed(self):
        values = {
            **self.valid,
            "csrf_trusted_origins": ["https://other.example.edu.cn"],
        }
        with self.assertRaisesMessage(ImproperlyConfigured, "not covered"):
            validate_production_secrets(**values)

    def test_short_backup_encryption_key_fails_closed(self):
        values = {**self.valid, "backup_encryption_key": "short"}
        with self.assertRaisesMessage(ImproperlyConfigured, "BACKUP_ENCRYPTION_KEY"):
            validate_production_secrets(**values)

    def test_long_but_low_entropy_secret_key_fails_closed(self):
        values = {**self.valid, "secret_key": "s" * 64}
        with self.assertRaisesMessage(ImproperlyConfigured, "character diversity"):
            validate_production_secrets(**values)


class RequiredExternalIntegrationGateTests(SimpleTestCase):
    configured = {
        "HR08_IAM": {
            "url": "https://iam.example.edu.cn/v1/accounts",
            "token": "iam-provider-token-value",
            "timeout": 10,
        },
        "HR08_ACADEMIC": {
            "url": "https://academic.example.edu.cn/v1/teachers",
            "token": "academic-provider-token-value",
            "timeout": 10,
        },
        "HR16_IAM": {
            "url": "https://iam.example.edu.cn/v1/exit",
            "token": "iam-provider-token-value",
            "timeout": 10,
        },
        "HR18_SUBMISSION": {
            "url": "https://edu.example.edu.cn/v1/submissions",
            "token": "submission-provider-token-value",
            "timeout": 15,
            "receipt_secret": "submission-receipt-secret-at-least-32-bytes",
            "receipt_key_id": "edu-2026-09",
        },
        "HR15_PAYMENT": {
            "url": "https://finance.example.edu.cn/v1/payments",
            "token": "payment-provider-token-value",
            "timeout": 15,
            "receipt_secret": "payment-receipt-secret-at-least-32-bytes",
            "receipt_key_id": "finance-2026-09",
            "provider_code": "UNIVERSITY_FINANCE",
        },
    }

    def test_declared_complete_integrations_pass(self):
        validate_required_external_integrations(
            {"HR16_IAM", "HR18_SUBMISSION"}, self.configured
        )

    def test_hr08_iam_and_academic_integrations_must_go_live_together(self):
        for required, missing in (
            ({"HR08_IAM"}, "HR08_ACADEMIC"),
            ({"HR08_ACADEMIC"}, "HR08_IAM"),
        ):
            with self.subTest(required=required):
                with self.assertRaisesMessage(ImproperlyConfigured, missing):
                    validate_required_external_integrations(
                        required, self.configured
                    )

        validate_required_external_integrations(
            {"HR08_IAM", "HR08_ACADEMIC"}, self.configured
        )

    def test_unknown_integration_fails_closed(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "unknown names"):
            validate_required_external_integrations({"UNKNOWN"}, self.configured)

    def test_declared_missing_integration_fails_closed(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "HR18_EXCHANGE"):
            validate_required_external_integrations(
                {"HR18_EXCHANGE"}, self.configured
            )

    def test_submission_requires_receipt_secret(self):
        configured = {
            **self.configured,
            "HR18_SUBMISSION": {
                **self.configured["HR18_SUBMISSION"],
                "receipt_secret": "short",
            },
        }
        with self.assertRaisesMessage(ImproperlyConfigured, "receipt HMAC"):
            validate_required_external_integrations(
                {"HR18_SUBMISSION"}, configured
            )

    def test_payment_requires_signed_receipt_and_provider_code(self):
        configured = {
            **self.configured,
            "HR15_PAYMENT": {
                **self.configured["HR15_PAYMENT"],
                "receipt_secret": "short",
                "provider_code": "bad-code",
            },
        }
        with self.assertRaises(ImproperlyConfigured) as caught:
            validate_required_external_integrations({"HR15_PAYMENT"}, configured)
        message = str(caught.exception)
        self.assertIn("HR15_PAYMENT receipt HMAC", message)
        self.assertIn("HR15_PAYMENT provider code", message)
