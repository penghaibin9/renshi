from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_standalone_installation_mode_is_explicit_and_documented():
    settings = read("backend/horilla/settings/base.py")
    env = read(".env.dist")
    assert 'HR_INSTALLATION_MODE = env("HR_INSTALLATION_MODE", default="standalone_school")' in settings
    assert 'HR_INSTALLATION_MODE=standalone_school' in env
    assert 'saas_platform' in settings


def test_professional_admin_health_is_secret_free_and_backup_read_only():
    source = read("backend/base/system_admin_health.py")
    assert "PRODUCTION_BACKUP_ROOT" in source
    assert "PRODUCTION_BACKUP_ENCRYPTION_KEY" in source
    assert 'latest_valid_manifest' in source
    assert 'FIELD_ENCRYPTION_KEYS' in source
    assert 'EMAIL_HOST_PASSWORD' not in source
    assert 'HR18_EXCHANGE_HTTP_TOKEN' not in source
    assert "create_production_backup" not in source
    assert "restore_production_backup" not in source


def test_single_school_center_has_professional_task_map_and_health_panel():
    template = read("backend/base/templates/base/settings/system_admin_center.html")
    for text in [
        "单校独立部署版",
        "学校基本信息",
        "账号与人员",
        "角色与权限",
        "组织与部门",
        "岗位与职务",
        "基础参数",
        "安全审计",
        "邮件与通知",
        "接口与同步",
        "运行与备份",
        "专业运行检查",
        "单校版按 6 步完成初始化",
        "角色优先",
        "最小权限",
        "危险操作不做“一键化”",
    ]:
        assert text in template


def test_single_school_center_does_not_expose_saas_operations():
    template = read("backend/base/templates/base/settings/system_admin_center.html")
    forbidden = ["套餐管理", "租户开通", "跨学校运营", "平台运营管理员"]
    for text in forbidden:
        assert text not in template


def test_health_status_is_derived_from_authoritative_sources():
    source = read("backend/base/system_admin_health.py")
    for token in [
        "Company.objects",
        "Department.objects",
        "JobPosition.objects",
        "DynamicEmailConfiguration.objects",
        'connection, "vendor"',
        "TWO_FACTORS_AUTHENTICATION",
        "PRODUCTION_BACKUP_ROOT",
    ]:
        assert token in source


def test_view_uses_scoped_account_metrics_and_health_service():
    source = read("backend/base/views.py")
    assert "build_system_admin_health" in source
    assert 'selected_company=selected_company' in source
    assert 'metrics=admin_metrics' in source
    assert 'users.filter(user_permissions__isnull=False)' in source


def test_admin_assistant_explains_single_school_organization_boundary():
    js = read("frontend/static/hr/js/core/hr-admin-center.js")
    assert "单校版第一次上线先配置什么？" in js
    assert "学院和部门应该建在哪里？" in js
    assert "不要把学院当成第二个 Company/学校主体" in js
    assert "yueke.hr.sysadmin.onboarding.v2" in js


def test_single_school_forms_prevent_second_school_and_auto_bind_departments():
    source = read("backend/base/forms.py")
    assert "allows exactly one school authority record" in source
    assert "Use departments for colleges and offices" in source
    assert "forms.MultipleHiddenInput()" in source
    assert "Automatically bound to the current school in standalone mode" in source


def test_standalone_readiness_has_server_side_check_command():
    source = read("backend/base/management/commands/check_school_system.py")
    assert "build_system_admin_health" in source
    assert "SCHOOL_SYSTEM_CHECK_OK" in source
    assert "READY_FOR_RUNTIME_ACCEPTANCE" in source
    assert "Standalone-school system check is blocked" in source


def test_standalone_does_not_publish_platform_operations_by_default():
    settings = read("backend/horilla/settings/base.py")
    env = read(".env.dist")
    urls = read("backend/horilla/urls.py")
    health = read("backend/base/system_admin_health.py")
    assert "PLATFORM_OPERATIONS_ENABLED" in settings
    assert "PLATFORM_OPERATIONS_ENABLED=False" in env
    assert 'if getattr(settings, "PLATFORM_OPERATIONS_ENABLED", False)' in urls
    assert 'include("platform_access.urls")' in urls
    assert "平台接口边界" in health


def test_standalone_superuser_bootstrap_is_bound_to_the_only_school():
    middleware = read("backend/platform_access/middleware.py")
    services = read("backend/platform_access/services.py")
    platform_tests = read("backend/platform_access/tests.py")
    assert 'HR_INSTALLATION_MODE' in middleware
    assert 'len(school_ids) == 1 and normalized == school_ids[0]' in middleware
    assert 'Standalone-school superuser may write only inside the single configured school.' in middleware
    assert 'PLATFORM_OPERATIONS_ENABLED' in services
    assert 'PLATFORM_OPERATIONS_ENABLED=True' in platform_tests
