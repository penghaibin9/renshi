from __future__ import annotations

import base64
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import TestCase, override_settings

from hr_integration.models import IntegrationConnection, SsoLoginEvidence
from hr_integration.sso_runtime import (
    SsoRuntimeError, _consume_flow, _flow, _oauth_claims, ldap_authenticate, record_evidence,
    safe_next, verify_id_token, runtime_contract_hash,
)


class SessionDict(dict):
    modified = False

class DummyRequest:
    def __init__(self): self.session = SessionDict()
    def get_host(self): return "hr.example.edu.cn"
    def is_secure(self): return True
    def build_absolute_uri(self, path): return "https://hr.example.edu.cn" + path


@override_settings(HR_INTEGRATION_ALLOWED_HOSTS=("sso.example.edu.cn",), HR_INTEGRATION_HTTP_TIMEOUT_SECONDS=2)
class SsoRuntimeSecurityTests(TestCase):
    def setUp(self):
        self.connection = IntegrationConnection.objects.create(
            tenant_id=9, code="OIDC", name="学校 OIDC", category="SSO", adapter_code="SSO_OIDC",
            base_url="https://sso.example.edu.cn", enabled=True,
            config_json={"client_id":"client","staff_no_claim":"employee_no"}, status="CONFIGURED",
        )

    def test_safe_next_rejects_external_redirect(self):
        req=DummyRequest()
        self.assertEqual(safe_next(req,"https://evil.example/steal"), "/")
        self.assertEqual(safe_next(req,"/hr/dashboard"), "/hr/dashboard")

    def test_state_is_one_time_and_expiring(self):
        req=DummyRequest(); flow=_flow(req,self.connection,next_url="/hr/")
        self.assertEqual(_consume_flow(req,self.connection,flow["state"])["next"],"/hr/")
        with self.assertRaises(SsoRuntimeError) as ctx: _consume_flow(req,self.connection,flow["state"])
        self.assertEqual(ctx.exception.code,"SSO_FLOW_MISSING")
        old=_flow(req,self.connection); req.session["hr_sso_flow_v1"]["created"]=int(time.time())-9999
        with self.assertRaises(SsoRuntimeError) as ctx: _consume_flow(req,self.connection,old["state"])
        self.assertEqual(ctx.exception.code,"SSO_FLOW_EXPIRED")

    def test_evidence_hashes_subject_and_is_append_only(self):
        row=record_evidence(self.connection,protocol="OIDC",status="SUCCESS",subject="sensitive-subject",staff_no="T001",user_id=4)
        self.assertNotEqual(row.subject_fingerprint,"sensitive-subject")
        self.assertEqual(len(row.subject_fingerprint),64)
        self.assertEqual(row.runtime_contract_hash, runtime_contract_hash(self.connection))
        self.assertEqual(len(row.runtime_contract_hash),64)
        self.assertNotIn("sensitive-subject",str(row.detail_json))
        with self.assertRaises(ValueError): SsoLoginEvidence.objects.filter(pk=row.pk).update(status="FAILED")


    def test_runtime_contract_change_invalidates_prior_acceptance_fingerprint(self):
        before = runtime_contract_hash(self.connection)
        self.connection.config_json = {**self.connection.config_json, "client_id": "rotated-client"}
        self.connection.save(update_fields=["config_json", "updated_at"])
        after = runtime_contract_hash(self.connection)
        self.assertNotEqual(before, after)

    def test_oidc_signature_audience_issuer_and_nonce_are_verified(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=key.public_key().public_numbers()
        enc=lambda n: base64.urlsafe_b64encode(n.to_bytes((n.bit_length()+7)//8,"big")).rstrip(b"=").decode()
        jwk={"kty":"RSA","kid":"k1","use":"sig","alg":"RS256","n":enc(public.n),"e":enc(public.e)}
        now=int(time.time())
        token=jwt.encode({"iss":"https://sso.example.edu.cn","aud":"client","sub":"u-1","nonce":"n-1","exp":now+300,"iat":now},key,algorithm="RS256",headers={"kid":"k1"})
        discovery={"issuer":"https://sso.example.edu.cn","authorization_endpoint":"https://sso.example.edu.cn/auth","token_endpoint":"https://sso.example.edu.cn/token","jwks_uri":"https://sso.example.edu.cn/jwks"}
        response=SimpleNamespace(status_code=200,json=lambda:{"keys":[jwk]})
        with patch("hr_integration.sso_runtime.oidc_discovery",return_value=discovery), patch("hr_integration.sso_runtime._request",return_value=response):
            claims=verify_id_token(self.connection,token,expected_nonce="n-1")
            self.assertEqual(claims["sub"],"u-1")
            with self.assertRaises(SsoRuntimeError) as ctx: verify_id_token(self.connection,token,expected_nonce="wrong")
            self.assertEqual(ctx.exception.code,"OIDC_NONCE_INVALID")


    def test_oidc_jwks_requires_http_200(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        now=int(time.time())
        token=jwt.encode({"iss":"https://sso.example.edu.cn","aud":"client","sub":"u-1","nonce":"n","exp":now+300,"iat":now},key,algorithm="RS256",headers={"kid":"k1"})
        discovery={"issuer":"https://sso.example.edu.cn","authorization_endpoint":"https://sso.example.edu.cn/auth","token_endpoint":"https://sso.example.edu.cn/token","jwks_uri":"https://sso.example.edu.cn/jwks"}
        response=SimpleNamespace(status_code=503,json=lambda:{"keys":[]})
        with patch("hr_integration.sso_runtime.oidc_discovery",return_value=discovery), patch("hr_integration.sso_runtime._request",return_value=response):
            with self.assertRaises(SsoRuntimeError) as ctx: verify_id_token(self.connection,token,expected_nonce="n")
            self.assertEqual(ctx.exception.code,"OIDC_JWKS_ERROR")

    def test_oauth_token_client_auth_supports_post_and_basic(self):
        oauth=IntegrationConnection.objects.create(tenant_id=9,code="OAUTH",name="OAuth",category="SSO",adapter_code="SSO_OAUTH2",base_url="https://sso.example.edu.cn",enabled=True,config_json={"client_id":"client","token_path":"/token","userinfo_path":"/userinfo","token_auth_method":"client_secret_post"})
        token_response=SimpleNamespace(status_code=200,json=lambda:{"access_token":"a"})
        user_response=SimpleNamespace(status_code=200,json=lambda:{"sub":"u","employee_no":"T1"})
        calls=[]
        def fake_request(method,url,**kwargs):
            calls.append((method,url,kwargs))
            return token_response if url.endswith("/token") else user_response
        with patch("hr_integration.sso_runtime._secrets",return_value={"client_secret":"secret"}), patch("hr_integration.sso_runtime._request",side_effect=fake_request):
            _oauth_claims(oauth,"code",{"redirect_uri":"https://hr.example.edu.cn/cb","verifier":"v"})
        self.assertEqual(calls[0][2]["data"]["client_secret"],"secret")
        self.assertNotIn("Authorization",calls[0][2]["headers"])
        oauth.config_json={**oauth.config_json,"token_auth_method":"client_secret_basic"}
        calls.clear()
        with patch("hr_integration.sso_runtime._secrets",return_value={"client_secret":"secret"}), patch("hr_integration.sso_runtime._request",side_effect=fake_request):
            _oauth_claims(oauth,"code",{"redirect_uri":"https://hr.example.edu.cn/cb","verifier":"v"})
        self.assertNotIn("client_secret",calls[0][2]["data"])
        self.assertTrue(calls[0][2]["headers"]["Authorization"].startswith("Basic "))

    def test_ldap_missing_reviewed_client_fails_closed(self):
        ldap=IntegrationConnection.objects.create(tenant_id=9,code="LDAP",name="LDAP",category="SSO",adapter_code="SSO_LDAP",enabled=True,config_json={"host":"sso.example.edu.cn","port":"636","base_dn":"dc=x","user_filter":"(uid={username})","staff_no_attribute":"employeeNumber","security_mode":"LDAPS"})
        with self.assertRaises(SsoRuntimeError) as ctx: ldap_authenticate(ldap,username="u",password="p")
        self.assertIn(ctx.exception.code,{"LDAP_CLIENT_MISSING","SSO_CREDENTIAL_DECRYPT_FAILED"})
