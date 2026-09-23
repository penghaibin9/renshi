#!/usr/bin/env python3
"""Local OIDC provider for CI acceptance only.

Never use this server in production. It exists to exercise Yueke HR's real
Authorization Code + PKCE + ID Token runtime through a browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

BIND_HOST = os.getenv("HR_SSO_MOCK_BIND_HOST", "127.0.0.1")
PUBLIC_HOST = os.getenv("HR_SSO_MOCK_PUBLIC_HOST", "localhost")
PORT = int(os.getenv("HR_SSO_MOCK_PORT", "9012"))
CLIENT_ID = os.getenv("HR_SSO_MOCK_CLIENT_ID", "hr-ci-oidc")
CLIENT_SECRET = os.getenv("HR_SSO_MOCK_CLIENT_SECRET", "hr-ci-oidc-secret")
SUBJECT = os.getenv("HR_SSO_MOCK_SUBJECT", "ci-subject-v1-auditor")
STAFF_NO = os.getenv("HR_SSO_MOCK_STAFF_NO", "V1-AUDITOR-001")
ISSUER = f"http://{PUBLIC_HOST}:{PORT}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CODES: dict[str, dict] = {}


def _enc(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode("ascii")


def _jwk():
    public = KEY.public_key().public_numbers()
    return {"kty":"RSA","kid":"ci-key","use":"sig","alg":"RS256","n":_enc(public.n),"e":_enc(public.e)}


class Handler(BaseHTTPRequestHandler):
    server_version = "YuekeMockOIDC/1.0"
    def log_message(self, fmt, *args):
        print("[mock-oidc]", fmt % args, flush=True)
    def _json(self, payload, status=200):
        body=json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        parsed=urlparse(self.path);q=parse_qs(parsed.query)
        if parsed.path=="/health": return self._json({"status":"ok"})
        if parsed.path=="/.well-known/openid-configuration":
            return self._json({"issuer":ISSUER,"authorization_endpoint":ISSUER+"/oidc/authorize","token_endpoint":ISSUER+"/oidc/token","jwks_uri":ISSUER+"/oidc/jwks"})
        if parsed.path=="/oidc/jwks": return self._json({"keys":[_jwk()]})
        if parsed.path=="/oidc/authorize":
            if q.get("client_id",[""])[0]!=CLIENT_ID: return self._json({"error":"invalid_client"},400)
            redirect_uri=q.get("redirect_uri",[""])[0];state=q.get("state",[""])[0]
            challenge=q.get("code_challenge",[""])[0];nonce=q.get("nonce",[""])[0]
            if not redirect_uri or not state or not challenge or q.get("code_challenge_method",[""])[0]!="S256":
                return self._json({"error":"invalid_request"},400)
            code="CI-"+secrets.token_urlsafe(18)
            CODES[code]={"redirect_uri":redirect_uri,"challenge":challenge,"nonce":nonce,"created":time.time()}
            location=redirect_uri+("&" if "?" in redirect_uri else "?")+urlencode({"code":code,"state":state})
            self.send_response(302);self.send_header("Location",location);self.end_headers();return
        self.send_response(404);self.end_headers()
    def do_POST(self):
        parsed=urlparse(self.path)
        if parsed.path!="/oidc/token": self.send_response(404);self.end_headers();return
        length=int(self.headers.get("Content-Length","0") or 0);data=parse_qs(self.rfile.read(length).decode())
        code=data.get("code",[""])[0];row=CODES.pop(code,None)
        if not row: return self._json({"error":"invalid_grant"},400)
        if time.time()-row["created"]>60: return self._json({"error":"expired_code"},400)
        verifier=data.get("code_verifier",[""])[0]
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not secrets.compare_digest(challenge,row["challenge"]): return self._json({"error":"pkce_failed"},400)
        post_secret=data.get("client_secret",[""])[0]
        basic=self.headers.get("Authorization","")
        expected="Basic "+base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        if post_secret!=CLIENT_SECRET and basic!=expected: return self._json({"error":"invalid_client"},401)
        if data.get("redirect_uri",[""])[0]!=row["redirect_uri"]: return self._json({"error":"redirect_mismatch"},400)
        now=int(time.time())
        token=jwt.encode({"iss":ISSUER,"aud":CLIENT_ID,"sub":SUBJECT,"employee_no":STAFF_NO,"preferred_username":STAFF_NO,"nonce":row["nonce"],"iat":now,"exp":now+300},KEY,algorithm="RS256",headers={"kid":"ci-key"})
        return self._json({"access_token":"CI-ACCESS","token_type":"Bearer","expires_in":300,"id_token":token})


if __name__=="__main__":
    print(f"mock OIDC listening on {ISSUER}",flush=True)
    ThreadingHTTPServer((BIND_HOST,PORT),Handler).serve_forever()
