from __future__ import annotations

import sys
import types
from contextlib import contextmanager

from django.test import TestCase, override_settings

from hr_integration.crypto import encrypt_secret_payload
from hr_integration.models import IntegrationConnection
from hr_integration.sso_runtime import SsoRuntimeError, ldap_authenticate


class _Attr:
    def __init__(self, value): self.value = value


class _Entry:
    entry_dn = "uid=teacher,ou=people,dc=example,dc=edu,dc=cn"
    uid = _Attr("teacher")
    employeeNumber = _Attr("T001")


class _FakeConnection:
    last_filter = ""
    def __init__(self, server, user=None, password=None, auto_bind=None, receive_timeout=None):
        if user == _Entry.entry_dn and password != "teacher-password":
            raise RuntimeError("invalid user password")
        self.entries = []
    def search(self, base_dn, search_filter, attributes=None, size_limit=None):
        type(self).last_filter = search_filter
        self.entries = [_Entry()]
        return True


@contextmanager
def fake_ldap3():
    called = {"escape": 0}
    ldap3 = types.ModuleType("ldap3")
    ldap3.AUTO_BIND_TLS_BEFORE_BIND = "STARTTLS"
    ldap3.AUTO_BIND_NO_TLS = "NO_TLS"
    ldap3.Server = lambda host, port, use_ssl, connect_timeout: object()
    ldap3.Connection = _FakeConnection
    utils = types.ModuleType("ldap3.utils")
    conv = types.ModuleType("ldap3.utils.conv")
    def escape_filter_chars(value):
        called["escape"] += 1
        return str(value).replace("*", r"\2a").replace("(", r"\28").replace(")", r"\29")
    conv.escape_filter_chars = escape_filter_chars
    old = {k: sys.modules.get(k) for k in ("ldap3", "ldap3.utils", "ldap3.utils.conv")}
    sys.modules.update({"ldap3": ldap3, "ldap3.utils": utils, "ldap3.utils.conv": conv})
    try: yield called
    finally:
        for key, value in old.items():
            if value is None: sys.modules.pop(key, None)
            else: sys.modules[key] = value


@override_settings(HR_INTEGRATION_ALLOWED_HOSTS=("ldap.example.edu.cn",))
class LdapLogicHarnessTests(TestCase):
    def _connection(self, mode="LDAPS"):
        return IntegrationConnection.objects.create(
            tenant_id=9001, code="LDAP", name="LDAP", category="SSO", adapter_code="SSO_LDAP",
            enabled=True, status="CONFIGURED",
            config_json={
                "host":"ldap.example.edu.cn", "port":"636" if mode == "LDAPS" else "389",
                "base_dn":"dc=example,dc=edu,dc=cn", "bind_dn":"cn=svc,dc=example,dc=edu,dc=cn",
                "user_filter":"(uid={username})", "username_attribute":"uid",
                "staff_no_attribute":"employeeNumber", "security_mode":mode,
            },
            secret_ciphertext=encrypt_secret_payload({"bind_password":"service-password"}),
        )

    def test_ldaps_logic_escapes_username_binds_user_and_returns_staff_number(self):
        connection = self._connection("LDAPS")
        with fake_ldap3() as called:
            claims = ldap_authenticate(connection, username="teacher*)(uid=*)", password="teacher-password")
        self.assertEqual(called["escape"], 1)
        self.assertIn(r"\2a", _FakeConnection.last_filter)
        self.assertEqual(claims["employeeNumber"], "T001")
        self.assertEqual(claims["sub"], "teacher*)(uid=*)")

    @override_settings(DEBUG=False, HR_SSO_ALLOW_INSECURE_FOR_TESTS=False)
    def test_plain_ldap_is_rejected_before_client_connection(self):
        connection = self._connection("PLAIN")
        with fake_ldap3():
            with self.assertRaises(SsoRuntimeError) as ctx:
                ldap_authenticate(connection, username="teacher", password="teacher-password")
        self.assertEqual(ctx.exception.code, "LDAP_TLS_REQUIRED")
