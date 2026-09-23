from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def read(path): return (ROOT/path).read_text(encoding="utf-8")


def test_infrastructure_apps_registered_without_hr19_hr20():
    settings=read("backend/horilla/settings/__init__.py")
    assert 'SYSTEM_HR_INFRA_APPS = ["hr_configuration", "hr_integration"]' in settings
    assert 'HR_INTEGRATION_ALLOWED_HOSTS' in settings
    assert 'HR19' not in read("backend/hr_configuration/apps.py")
    assert 'HR20' not in read("backend/hr_integration/apps.py")


def test_root_routes_and_system_admin_entry_are_present():
    urls=read("backend/horilla/urls.py")
    assert 'include("hr_configuration.urls")' in urls
    assert 'include("hr_integration.urls")' in urls
    page=read("backend/base/templates/base/settings/system_admin_center.html")
    assert "hr-configuration-center" in page
    assert "hr-integration-hub" in page
    assert "数据上报与交换" in page


def test_configuration_center_covers_all_eight_requested_layers():
    models=read("backend/hr_configuration/models.py")
    for symbol in ["WorkflowStage","FormDefinition","FieldDefinition","ApprovalRoleRule","ConditionRule","NotificationRule","PrintTemplate","ExcelTemplate"]:
        assert f"class {symbol}" in models
    services=read("backend/hr_configuration/services.py")
    assert '"contentHash"' in services
    assert "HRCFG_PUBLISHED_IMMUTABLE" in models


def test_adapter_catalog_covers_requested_school_interfaces():
    adapters=read("backend/hr_integration/adapters.py")
    for code in ["SSO_CAS","SSO_OAUTH2","SSO_OIDC","SSO_LDAP","MASTERDATA_HTTP_JSON","RESEARCH_HTTP_JSON","ACADEMIC_HTTP_JSON","FINANCE_HTTP_JSON","ATTENDANCE_HTTP_JSON","ESIGN_HTTP_JSON","SMS_HTTP","EMAIL_SMTP","WECOM"]:
        assert code in adapters
    assert "HOST_NOT_ALLOWED" in adapters


def test_credentials_are_write_only_and_encrypted():
    crypto=read("backend/hr_integration/crypto.py")
    template=read("backend/hr_integration/templates/hr_integration/connection_detail.html")
    assert "encrypt_text" in crypto and "FIELD_ENCRYPTION_KEYS" in crypto
    assert "credential_text" not in template
    assert "已加密保存" in template


def test_business_modules_get_one_stable_school_contract_facade():
    facade=read("backend/horilla/hr_school_contracts.py")
    assert "def school_workflow" in facade
    assert "def school_integration" in facade
    assert "get_published_workflow_config" in facade
    assert "connection_contract" in facade
