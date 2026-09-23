from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_system_admin_center_is_first_class_route_and_menu():
    assert 'name="system-admin-center"' in read("backend/base/urls.py")
    sidebar = read("backend/base/sidebar.py")
    assert 'reverse_lazy("system-admin-center")' in sidebar
    assert '"System Management Center"' in sidebar

def test_system_admin_center_is_task_first_and_covers_core_admin_jobs():
    tpl = read("backend/base/templates/base/settings/system_admin_center.html")
    assert "我要设置什么" in tpl
    for label in ["账号与人员","角色与权限","组织与部门","岗位与职务","基础参数","安全审计","邮件与通知","接口与同步"]:
        assert label in tpl

def test_system_admin_onboarding_progress_cannot_be_mistaken_for_acceptance():
    tpl = read("backend/base/templates/base/settings/system_admin_center.html")
    js = read("frontend/static/hr/js/core/hr-admin-center.js")
    assert tpl.count("data-check=") >= 6
    assert "不代表正式验收通过" in tpl
    assert "localStorage" in js

def test_high_risk_delete_permissions_require_confirmation_and_preview():
    perm = read("backend/base/templates/base/auth/permission_table.html")
    detail = read("backend/horilla_theme/templates/base/auth/group_detail.html")
    js = read("frontend/static/hr/js/core/hr-admin-center.js")
    assert 'data-permission-risk="high"' in perm
    assert "sysadmin-role-risk" in detail
    assert "高风险删除权限" in js
    assert "window.confirm" in js

def test_admin_center_scopes_hr18_link_by_permission_and_does_not_fake_runtime_acceptance():
    views = read("backend/base/views.py")
    tpl = read("backend/base/templates/base/settings/system_admin_center.html")
    assert 'has_perm("hr.data.exchange")' in views
    assert "admin_can_hr18_exchange" in tpl
    assert "不能用 mock 当通过" in tpl
    assert "服务器执行" in tpl

def test_system_admin_assets_are_shipped_from_master_template():
    index = read("frontend/templates/index.html")
    assert "hr-admin-center.css" in index
    assert "hr-admin-center.js" in index
