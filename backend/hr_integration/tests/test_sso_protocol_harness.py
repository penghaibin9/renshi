from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import TestCase, override_settings

from hr_integration.crypto import encrypt_secret_payload
from hr_integration.models import IntegrationConnection
from hr_integration.sso_runtime import _cas_claims, _oauth_claims, begin_url, oidc_discovery


class _State:
    client_id = "acceptance-client"
    client_secret = "acceptance-secret"
    verifier = "acceptance-verifier"
    nonce = "acceptance-nonce"
    subject = "subject-T001"
    staff_no = "T001"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @classmethod
    def jwk(cls):
        public = cls.key.public_key().public_numbers()
        enc = lambda n: base64.urlsafe_b64encode(
            n.to_bytes((n.bit_length() + 7) // 8, "big")
        ).rstrip(b"=").decode("ascii")
        return {
            "kty": "RSA", "kid": "acceptance-key", "use": "sig", "alg": "RS256",
            "n": enc(public.n), "e": enc(public.e),
        }


class _Handler(BaseHTTPRequestHandler):
    server_version = "YuekeMockIdP/1.0"

    def log_message(self, *_args):
        return

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def _json(self, payload, code=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/cas/login":
            self.send_response(302)
            self.send_header("Location", query.get("service", ["/"])[0] + "&ticket=ST-ACCEPTANCE")
            self.end_headers()
            return
        if parsed.path == "/cas/serviceValidate":
            ticket = query.get("ticket", [""])[0]
            if ticket != "ST-ACCEPTANCE":
                body = b'<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas"><cas:authenticationFailure code="INVALID_TICKET">bad</cas:authenticationFailure></cas:serviceResponse>'
            else:
                body = (
                    '<cas:serviceResponse xmlns:cas="http://www.yale.edu/tp/cas">'
                    '<cas:authenticationSuccess><cas:user>subject-T001</cas:user>'
                    '<cas:attributes><cas:employeeNo>T001</cas:employeeNo></cas:attributes>'
                    '</cas:authenticationSuccess></cas:serviceResponse>'
                ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/oauth/userinfo":
            if self.headers.get("Authorization") != "Bearer AT-ACCEPTANCE":
                return self._json({"error": "unauthorized"}, 401)
            return self._json({"sub": _State.subject, "employee_no": _State.staff_no})
        if parsed.path == "/.well-known/openid-configuration":
            return self._json({
                "issuer": self.base,
                "authorization_endpoint": self.base + "/oidc/authorize",
                "token_endpoint": self.base + "/oidc/token",
                "jwks_uri": self.base + "/oidc/jwks",
            })
        if parsed.path == "/oidc/jwks":
            return self._json({"keys": [_State.jwk()]})
        if parsed.path in {"/oauth/authorize", "/oidc/authorize"}:
            # Endpoint exists for begin_url reachability. Browser redirection is
            # exercised by production Playwright/MySQL gate, not this unit harness.
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        data = parse_qs(self.rfile.read(length).decode("utf-8"))
        if parsed.path not in {"/oauth/token", "/oidc/token"}:
            self.send_response(404); self.end_headers(); return
        if data.get("code_verifier", [""])[0] != _State.verifier:
            return self._json({"error": "invalid_grant"}, 400)
        post_secret = data.get("client_secret", [""])[0]
        basic = self.headers.get("Authorization", "")
        expected_basic = "Basic " + base64.b64encode(
            f"{_State.client_id}:{_State.client_secret}".encode("utf-8")
        ).decode("ascii")
        if post_secret != _State.client_secret and basic != expected_basic:
            return self._json({"error": "invalid_client"}, 401)
        if parsed.path == "/oauth/token":
            return self._json({"access_token": "AT-ACCEPTANCE", "token_type": "Bearer"})
        now = int(time.time())
        id_token = jwt.encode({
            "iss": self.base, "aud": _State.client_id, "sub": _State.subject,
            "employee_no": _State.staff_no, "nonce": _State.nonce,
            "iat": now, "exp": now + 300,
        }, _State.key, algorithm="RS256", headers={"kid": "acceptance-key"})
        return self._json({"access_token": "AT-ACCEPTANCE", "id_token": id_token, "token_type": "Bearer"})


class MockIdP:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)


@override_settings(
    DEBUG=True,
    HR_SSO_ALLOW_INSECURE_FOR_TESTS=True,
    HR_INTEGRATION_ALLOWED_HOSTS=("127.0.0.1",),
    HR_INTEGRATION_HTTP_TIMEOUT_SECONDS=2,
    ROOT_URLCONF="hr_integration.tests.harness_urls",
)
class RealProtocolHarnessTests(TestCase):
    def _connection(self, code, adapter, base, config, secret=None):
        return IntegrationConnection.objects.create(
            tenant_id=9001, code=code, name=code, category="SSO", adapter_code=adapter,
            base_url=base, enabled=True, status="CONFIGURED", config_json=config,
            secret_ciphertext=encrypt_secret_payload(secret or {}) if secret else "",
        )

    def test_cas_validate_uses_real_http_and_extracts_staff_number(self):
        with MockIdP() as idp:
            connection = self._connection("CAS", "SSO_CAS", idp.base, {
                "login_path": "/cas/login", "validate_path": "/cas/serviceValidate",
                "service_parameter": "service", "staff_no_claim": "employeeNo",
            })
            claims = _cas_claims(connection, "ST-ACCEPTANCE", "https://hr.example.edu.cn/sso/callback")
        self.assertEqual(claims["user"], _State.subject)
        self.assertEqual(claims["employeeNo"], _State.staff_no)

    def test_oauth2_token_pkce_and_userinfo_use_real_http(self):
        with MockIdP() as idp:
            connection = self._connection("OAUTH", "SSO_OAUTH2", idp.base, {
                "authorize_path": "/oauth/authorize", "token_path": "/oauth/token",
                "userinfo_path": "/oauth/userinfo", "client_id": _State.client_id,
                "token_auth_method": "client_secret_post", "subject_claim": "sub",
                "staff_no_claim": "employee_no",
            }, {"client_secret": _State.client_secret})
            claims = _oauth_claims(connection, "AUTH-CODE", {
                "redirect_uri": "https://hr.example.edu.cn/sso/callback",
                "verifier": _State.verifier,
            })
        self.assertEqual(claims["sub"], _State.subject)
        self.assertEqual(claims["employee_no"], _State.staff_no)

    def test_oidc_discovery_jwks_signature_nonce_and_pkce_use_real_http(self):
        with MockIdP() as idp:
            connection = self._connection("OIDC", "SSO_OIDC", idp.base, {
                "client_id": _State.client_id, "discovery_path": "/.well-known/openid-configuration",
                "scope": "openid profile", "token_auth_method": "client_secret_basic",
                "staff_no_claim": "employee_no",
            }, {"client_secret": _State.client_secret})
            document = oidc_discovery(connection)
            self.assertEqual(document["issuer"], idp.base)
            claims = _oauth_claims(connection, "OIDC-CODE", {
                "redirect_uri": "https://hr.example.edu.cn/sso/callback",
                "verifier": _State.verifier, "nonce": _State.nonce,
            }, oidc=True)
        self.assertEqual(claims["sub"], _State.subject)
        self.assertEqual(claims["employee_no"], _State.staff_no)

    def test_begin_url_generates_pkce_state_without_exposing_secret(self):
        class Session(dict): modified = False
        class Request:
            session = Session()
            def get_host(self): return "hr.example.edu.cn"
            def is_secure(self): return True
            def build_absolute_uri(self, path): return "https://hr.example.edu.cn" + path
        with MockIdP() as idp:
            connection = self._connection("OAUTH-BEGIN", "SSO_OAUTH2", idp.base, {
                "authorize_path": "/oauth/authorize", "token_path": "/oauth/token",
                "userinfo_path": "/oauth/userinfo", "client_id": _State.client_id,
                "scope": "profile", "token_auth_method": "client_secret_post",
                "subject_claim": "sub", "staff_no_claim": "employee_no",
            }, {"client_secret": _State.client_secret})
            url = begin_url(Request(), connection, next_url="/hr/")
        parsed = urlparse(url); query = parse_qs(parsed.query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(query["code_challenge"][0])
        self.assertTrue(query["state"][0])
        self.assertNotIn(_State.client_secret, url)
