from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from hr_integration.adapters import probe


@override_settings(HR_INTEGRATION_ALLOWED_HOSTS=("sso.example.edu.cn",), HR_INTEGRATION_HTTP_TIMEOUT_SECONDS=2)
class SsoAdapterProbeTests(SimpleTestCase):
    @patch("hr_integration.adapters.requests.get")
    def test_cas_probe_validates_login_endpoint_without_claiming_user_login(self, get):
        get.return_value = Mock(status_code=302)
        result = probe(
            category="SSO", adapter_code="SSO_CAS", base_url="https://sso.example.edu.cn",
            config={"login_path":"/cas/login", "validate_path":"/cas/serviceValidate", "staff_no_claim":"user"}, secrets={},
        )
        self.assertEqual(result["status"], "CONFIG_VALIDATED")
        self.assertIn("Ticket", result["summary"])
        self.assertTrue(get.call_args.args[0].endswith("/cas/login"))

    @patch("hr_integration.adapters.requests.get")
    def test_oauth_authorize_400_still_proves_endpoint_reachability(self, get):
        get.return_value = Mock(status_code=400)
        result = probe(
            category="SSO", adapter_code="SSO_OAUTH2", base_url="https://sso.example.edu.cn",
            config={"authorize_path":"/oauth/authorize", "token_path":"/oauth/token", "userinfo_path":"/oauth/userinfo", "client_id":"client", "subject_claim":"sub", "staff_no_claim":"employee_no"},
            secrets={"client_secret":"secret"},
        )
        self.assertEqual(result["status"], "CONFIG_VALIDATED")
        self.assertIn("授权码", result["summary"])

    @patch("hr_integration.adapters.requests.get")
    def test_oidc_discovery_requires_standard_metadata(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {
            "issuer":"https://sso.example.edu.cn",
            "authorization_endpoint":"https://sso.example.edu.cn/authorize",
            "token_endpoint":"https://sso.example.edu.cn/token",
            "jwks_uri":"https://sso.example.edu.cn/jwks",
        }
        get.return_value = response
        result = probe(
            category="SSO", adapter_code="SSO_OIDC", base_url="https://sso.example.edu.cn",
            config={"client_id":"client", "discovery_path":"/.well-known/openid-configuration", "staff_no_claim":"employee_no"},
            secrets={"client_secret":"secret"},
        )
        self.assertEqual(result["status"], "CONFIG_VALIDATED")
        self.assertIn("Discovery", result["summary"])
