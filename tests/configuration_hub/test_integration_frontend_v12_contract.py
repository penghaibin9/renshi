from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_professional_integration_hub_frontend_exists_without_new_hr_module():
    hub = read("backend/hr_integration/templates/hr_integration/hub.html")
    assert "统一认证与接口适配中心" in hub
    assert "hr-integration-create" in hub
    for protocol in ["CAS", "OAuth2", "OIDC", "LDAP"]:
        assert protocol in read("backend/hr_integration/ui_catalog.py")
    settings = read("backend/horilla/settings/__init__.py")
    assert 'SYSTEM_HR_INFRA_APPS = ["hr_configuration", "hr_integration"]' in settings


def test_school_staff_do_not_need_to_edit_json_for_normal_sso_setup():
    partial = read("backend/hr_integration/templates/hr_integration/partials/connection_form.html")
    js = read("backend/hr_integration/static/hr_integration/integration_hub_v2.js")
    assert "协议参数" in partial and "凭据与密钥" in partial
    assert "高级配置 JSON" in partial
    assert "data-hrint-config-fields" in partial
    assert "data-hrint-secret-fields" in partial
    assert "高级配置 JSON（仅实施工程师 / AI 使用）" in partial
    assert "credentialText.value" in js


def test_sso_frontend_explains_materials_mapping_and_real_verification_scope():
    ui = read("backend/hr_integration/ui_catalog.py")
    detail = read("backend/hr_integration/templates/hr_integration/connection_detail.html")
    for text in ["学校信息处需要提供", "当前验证范围", "Claims 字典", "Base DN", "Client ID / Client Secret"]:
        assert text in ui or text in detail
    assert "外部身份 / 业务字段 → 跃科标准字段" in detail
    assert "真实 Ticket 登录" in ui
    assert "授权码" in ui


def test_sso_probe_is_protocol_aware_and_does_not_claim_real_login():
    adapters = read("backend/hr_integration/adapters.py")
    assert 'adapter_code in {"SSO_CAS", "SSO_OAUTH2", "SSO_OIDC"}' in adapters
    assert "OIDC Discovery" in adapters
    assert "CONFIG_VALIDATED" in adapters
    assert "待真实 Ticket 登录验收" in adapters
    assert "待授权码登录回放" in adapters


def test_adapter_switch_cannot_reuse_old_secret_contract():
    services = read("backend/hr_integration/services.py")
    assert "adapter_changed" in services
    assert 'obj.secret_ciphertext=""' in services
    assert "Never silently reuse an old" in services


def test_existing_mysql_browser_gate_now_uses_guided_frontend():
    script = read("scripts/hr_config_integration_browser.py")
    assert "/settings/integration-hub/new/?adapter=MASTERDATA_HTTP_JSON" in script
    assert 'data-hrint-key="health_path"' in script
    assert 'data-hrint-key="token"' in script
    assert "CI-TOP-SECRET" in script
