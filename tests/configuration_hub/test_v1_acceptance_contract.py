from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_mysql_84_browser_gate_exists_and_is_not_sqlite_substitute():
    workflow = read(".github/workflows/hr-config-integration-v1.yml")
    assert "image: mysql:8.4" in workflow
    assert "database_vendor" in workflow and '== "mysql"' in workflow
    assert "bootstrap_hr_configuration_v1" in workflow
    assert "hr_config_integration_browser.py" in workflow
    assert "verify_hr_config_integration_v1.py" in workflow


def test_browser_gate_uses_real_login_and_all_requested_configuration_layers():
    script = read("scripts/hr_config_integration_browser.py")
    assert 'page.goto(BASE_URL + "/login/"' in script
    assert 'button[type="submit"]' in script
    for text in ["添加字段", "添加审批角色", "添加条件", "添加通知", "添加打印模板", "添加 Excel 模板", "添加 Excel 列"]:
        assert text in script
    assert "publish-eight-layer-config" in script


def test_integration_gate_uses_allowlisted_real_http_probe_and_secret_never_expected_in_contract():
    browser = read("scripts/hr_config_integration_browser.py")
    mock = read("scripts/hr_config_integration_mock_school.py")
    workflow = read(".github/workflows/hr-config-integration-v1.yml")
    assert 'http://127.0.0.1:9011' in browser
    assert '"/health"' in mock
    assert "HR_INTEGRATION_ALLOWED_HOSTS: 127.0.0.1,localhost" in workflow
    assert '"CI-TOP-SECRET" not in serialized' in browser


def test_database_verifier_checks_published_hash_mapping_encryption_and_verified_status():
    verifier = read("scripts/verify_hr_config_integration_v1.py")
    for token in ["content_hash", "IntegrationConnection.Status.VERIFIED", "secret_ciphertext", "IntegrationFieldMapping", "contractHash"]:
        assert token in verifier


def test_v1_acceptance_gate_does_not_modify_hr01_hr18_business_modules():
    workflow = read(".github/workflows/hr-config-integration-v1.yml")
    browser = read("scripts/hr_config_integration_browser.py")
    assert "hr_configuration" in workflow and "hr_integration" in workflow
    for banned in ["hr_recruitment/models.py", "hr_onboarding/models.py", "hr_payroll/models.py", "hr_exit/models.py"]:
        assert banned not in workflow
        assert banned not in browser


def test_school_implementation_gate_requires_mysql_84_and_real_completion_evidence():
    command = read("backend/hr_configuration/management/commands/hr_config_integration_v1_gate.py")
    assert 'connection.vendor != "mysql"' in command
    assert 'mysql_version.startswith("8.4.")' in command
    assert 'PUBLISHED_CONFIG_REQUIRED' in command
    assert 'VERIFIED_INTEGRATION_REQUIRED' in command
    assert 'FIELD_MAPPING_REQUIRED' in command
    workflow = read(".github/workflows/hr-config-integration-v1.yml")
    assert "hr_config_integration_v1_gate" in workflow
    assert "--require-published HR05" in workflow
    assert "--require-verified MASTER_DATA" in workflow
