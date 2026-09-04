from pathlib import Path
import re

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve


class SharedHrWorkspaceShellContractTests(SimpleTestCase):
    def _source(self, relative_path: str) -> str:
        root = (
            Path(settings.FRONTEND_DIR)
            if relative_path.startswith(("templates/", "static/"))
            else Path(settings.BACKEND_DIR)
        )
        return (root / relative_path).read_text(encoding="utf-8")

    def test_root_template_renders_child_workspace_scripts(self):
        source = self._source("templates/index.html")

        self.assertIn("{% block scripts %}", source)
        self.assertIn("{% endblock scripts %}", source)
        self.assertLess(source.index("{% block scripts %}"), source.index("</body>"))

    def test_shell_timer_scripts_default_missing_work_seconds_to_zero(self):
        timer_expression = (
            "{{ request.user.employee_get.get_forecasted_at_work."
            'forecasted_at_work_seconds|default:"0" }};'
        )

        for template_path in (
            "templates/index.html",
            "horilla_theme/templates/horilla_theme/components/header_scripts.html",
        ):
            with self.subTest(template_path=template_path):
                source = self._source(template_path)
                self.assertIn(f"var at_work_seconds = {timer_expression}", source)
                self.assertIn("var run = 0;", source)

    def test_mobile_shell_uses_native_closed_state_not_dom_removal(self):
        source = self._source("static/src/js/customHeaderScripts.js")

        self.assertIn("const MOBILE_QUERY = '(max-width: 767.98px)'", source)
        self.assertIn("localStorage.setItem('sidebarOpen', 'false')", source)
        self.assertIn("shell.classList.add('oh-wrapper-main--closed')", source)
        self.assertIn(
            "document.addEventListener('DOMContentLoaded', initialiseResponsiveShell)",
            source,
        )
        self.assertIn("window.addEventListener('load', initialiseResponsiveShell)", source)
        self.assertIn("document.querySelector('.oh-navbar__toggle-link')", source)
        self.assertIn("restoreDesktopSidebarState", source)
        self.assertNotIn("sidebar.style.display", source)
        self.assertNotIn("shell.remove()", source)

    def test_every_hr_module_has_a_sidebar_secondary_navigation_contract(self):
        source = self._source("templates/hr/components/module_sidebar.html")
        expected_labels = (
            "人事工作台二级页面",
            "组织岗位二级页面",
            "教职工主档二级页面",
            "招聘管理二级页面",
            "入职管理二级页面",
            "人事异动二级页面",
            "合同管理二级页面",
            "外聘人员二级页面",
            "资格资质二级页面",
            "教师发展二级页面",
            "考勤时间二级页面",
            "考核管理二级页面",
            "职称评审二级页面",
            "岗位聘任二级页面",
            "薪酬福利二级页面",
            "退休离校二级页面",
            "教职工服务二级页面",
            "人事数据中心二级页面",
        )
        for label in expected_labels:
            with self.subTest(label=label):
                self.assertIn(f'aria-label="{label}"', source)

        self.assertEqual(source.count('class="hr-module-nav__subnav"'), 18)
        self.assertIsNone(
            re.search(
                r"\{% if [^%]+ %\}\s*<div class=\"hr-module-nav__subnav\"",
                source,
            ),
            "Secondary navigation must be rendered for every module, not only the active one.",
        )
        self.assertIn('link.setAttribute("aria-expanded"', source)
        self.assertIn('link.setAttribute("aria-controls"', source)
        self.assertIn('subnav.classList.toggle("is-open"', source)

        stylesheet = self._source("static/hr/css/hr-shell-v3.css")
        self.assertIn(".hr-module-nav__subnav.is-open", stylesheet)

    def test_every_static_hr_sidebar_link_resolves_to_a_real_route(self):
        source = self._source("templates/hr/components/module_sidebar.html")
        urls = sorted(set(re.findall(r'href="(/hr/[^"{]*)"', source)))
        self.assertGreaterEqual(len(urls), 70)
        unresolved = []
        for url in urls:
            try:
                resolve(url)
            except Resolver404:
                unresolved.append(url)
        self.assertEqual(unresolved, [], f"侧栏存在无效二级入口: {unresolved}")
