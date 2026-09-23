from __future__ import annotations
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
CHECKS = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    CHECKS.append(name)

def text(path):
    return (ROOT / path).read_text(encoding="utf-8")

def main():
    urls=text("backend/base/urls.py"); views=text("backend/base/views.py"); sidebar=text("backend/base/sidebar.py")
    tpl=text("backend/base/templates/base/settings/system_admin_center.html")
    settings_tpl=text("backend/horilla_theme/templates/settings.html")
    role_tpl=text("backend/horilla_theme/templates/base/auth/group_detail.html")
    perm_tpl=text("backend/base/templates/base/auth/permission_table.html")
    index=text("frontend/templates/index.html"); js=text("frontend/static/hr/js/core/hr-admin-center.js"); css=text("frontend/static/hr/css/hr-admin-center.css")
    check("route", 'name="system-admin-center"' in urls)
    check("view", "def system_admin_center_view" in views and "_system_admin_center_allowed" in views)
    check("view fail closed", "raise PermissionDenied" in views)
    check("menu first", '"System Management Center"' in sidebar and 'reverse_lazy("system-admin-center")' in sidebar)
    check("task first", "我要设置什么" in tpl and "sysadmin-task-search" in tpl)
    for phrase in ["账号与人员","角色与权限","组织与部门","岗位与职务","基础参数","安全审计","邮件与通知","接口与同步"]:
        check("task:"+phrase, phrase in tpl)
    check("metrics", "accounts_without_role" in views and "direct_permission_accounts" in views)
    check("six step onboarding", tpl.count('data-check=') >= 6 and "不代表正式验收通过" in tpl)
    check("ops boundaries", "生产备份" in tpl and "学校数据移交" in tpl and "最终验收包" in tpl)
    check("assistant prompts", tpl.count('class="sysadmin-prompts"') == 1 and tpl.count('<button type="button">') >= 12)
    check("assistant no pii", "身份证" not in js and "工资" not in js)
    check("search aliases", "开账号" in tpl and "配角色" in tpl and "查日志" in tpl and "备份" in tpl)
    check("checklist local only", "localStorage" in js and "不代表正式验收" in tpl)
    check("risk data attribute", 'data-permission-risk="high"' in perm_tpl)
    check("role risk preview", "sysadmin-role-risk" in role_tpl and "permissionRiskSummary" in js)
    check("danger confirm", "高风险删除权限" in js and "window.confirm" in js)
    check("settings chinese usability", "搜索设置，例如：权限、部门、邮件" in settings_tpl and "系统管理" in settings_tpl)
    check("assets css", "hr-admin-center.css" in index and len(css)>2000)
    check("assets js", "hr-admin-center.js" in index and len(js)>3000)
    check("HR18 permission gate", "admin_can_hr18_exchange" in views and "admin_can_hr18_exchange" in tpl)
    check("no mock acceptance", "不能用 mock 当通过" in tpl and "服务器执行" in tpl)
    for path in ["backend/base/views.py","backend/base/sidebar.py","backend/base/urls.py"]:
        ast.parse(text(path))
        check("ast:"+path, True)
    print(f"System admin usability contract: {len(CHECKS)}/{len(CHECKS)} PASS")
    for item in CHECKS: print("PASS", item)

if __name__ == "__main__": main()
