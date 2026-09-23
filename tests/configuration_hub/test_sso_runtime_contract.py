from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def read(path): return (ROOT/path).read_text(encoding='utf-8')

def test_sso_runtime_supports_required_protocols_and_pkce_state_nonce():
    src=read('backend/hr_integration/sso_runtime.py')
    for token in ['SSO_CAS','SSO_OAUTH2','SSO_OIDC','SSO_LDAP','code_challenge_method','S256','OIDC_NONCE_INVALID','SSO_STATE_INVALID']:
        assert token in src

def test_identity_resolution_reuses_hr03_and_never_creates_users_or_roles():
    src=read('backend/hr_integration/sso_runtime.py')
    for token in ['HrStaffMaster','HrEmploymentRelationship','HrAccountLink','HrExternalIdentityMapping','get_allowed_company_ids']:
        assert token in src
    assert 'create_user(' not in src
    assert 'create_superuser(' not in src
    assert 'user_permissions.add' not in src

def test_oidc_verifies_signature_issuer_audience_nonce_and_allowlisted_network():
    src=read('backend/hr_integration/sso_runtime.py')
    for token in ['jwt.decode','audience=cfg["client_id"]','issuer=doc["issuer"]','expected_nonce','_require_allowed_host']:
        assert token in src

def test_ldap_requires_tls_and_safe_local_next():
    src=read('backend/hr_integration/sso_runtime.py')
    views=read('backend/hr_integration/sso_views.py')
    assert 'LDAP_TLS_REQUIRED' in src
    assert 'AUTO_BIND_TLS_BEFORE_BIND' in src
    assert 'safe_next(request' in views
    assert 'LDAP_CLIENT_MISSING' in src

def test_tokens_passwords_and_full_claims_are_not_persisted_in_evidence():
    models=read('backend/hr_integration/models.py')
    runtime=read('backend/hr_integration/sso_runtime.py')
    assert 'SsoLoginEvidence' in models
    assert 'subject_fingerprint' in models
    for forbidden in ['access_token = models.', 'id_token = models.', 'ticket = models.', 'password = models.', 'claims_json']:
        assert forbidden not in models
    assert 'hashlib.sha256(subject.encode' in runtime

def test_login_page_and_logout_are_runtime_aware():
    base=read('backend/base/views.py')
    login=read('backend/horilla_theme/templates/login.html')
    urls=read('backend/hr_integration/urls.py')
    assert 'public_sso_connections' in base
    assert 'hr_sso_connection_id' in base
    assert 'sso_options' in login
    assert 'hr-sso-callback' in urls and 'hr-sso-logout' in urls

def test_implementation_gate_can_require_real_sso_success_evidence():
    gate=read('backend/hr_configuration/management/commands/hr_config_integration_v1_gate.py')
    assert '--require-sso-runtime' in gate
    assert 'SSO_RUNTIME_LOGIN_EVIDENCE_REQUIRED' in gate
    assert 'SsoLoginEvidence.Status.SUCCESS' in gate
