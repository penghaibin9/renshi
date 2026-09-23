from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_protocol_harness_is_test_only_and_exercises_real_http():
    text = read("backend/hr_integration/tests/test_sso_protocol_harness.py")
    assert "ThreadingHTTPServer" in text
    assert "_cas_claims" in text and "_oauth_claims" in text and "oidc_discovery" in text
    assert "HR_SSO_ALLOW_INSECURE_FOR_TESTS=True" in text
    assert "127.0.0.1" in text


def test_ci_mock_oidc_uses_pkce_and_separate_hostname_from_django_cookie_scope():
    text = read("scripts/hr_sso_mock_oidc.py")
    assert 'PUBLIC_HOST = os.getenv("HR_SSO_MOCK_PUBLIC_HOST", "localhost")' in text
    assert 'BIND_HOST = os.getenv("HR_SSO_MOCK_BIND_HOST", "127.0.0.1")' in text
    assert "code_challenge" in text and "code_verifier" in text
    assert "S256" in text
    assert "sessionid" not in text


def test_browser_gate_uses_public_sso_button_and_logout():
    text = read("scripts/hr_sso_runtime_browser.py")
    assert "a.yk-login-submit--sso" in text
    assert "/sso/logout/" in text
    assert "#password" not in text


def test_preflight_does_not_print_secret_values_and_supports_live_ready():
    text = read("backend/hr_integration/management/commands/hr_sso_school_preflight.py")
    assert "--require-live-ready" in text
    assert "runtime_contract_hash" in text
    assert "schoolMaterials" in text
    assert "decrypt_secret_payload" in text
    assert '"secrets": secrets' not in text
    assert '"client_secret"' not in text
    assert '"bind_password"' not in text


def test_runtime_evidence_is_bound_to_current_contract():
    runtime = read("backend/hr_integration/sso_runtime.py")
    gate = read("backend/hr_configuration/management/commands/hr_config_integration_v1_gate.py")
    model = read("backend/hr_integration/models.py")
    assert "def runtime_contract_hash" in runtime
    assert "credentialUpdatedAt" in runtime
    assert "runtime_contract_hash" in model
    assert "SSO_RUNTIME_LOGIN_EVIDENCE_REQUIRED_FOR_CURRENT_CONTRACT" in gate


def test_mysql_ci_runs_real_browser_sso_and_live_preflight():
    text = read(".github/workflows/hr-config-integration-v1.yml")
    assert "scripts/hr_sso_mock_oidc.py" in text
    assert "scripts/hr_sso_runtime_browser.py" in text
    assert "hr_sso_school_preflight" in text
    assert "--require-live-ready" in text
    assert "--require-sso-runtime" in text
    assert "HR_SSO_PUBLIC_TENANT_ID" in text
