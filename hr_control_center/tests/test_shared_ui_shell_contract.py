from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SharedHrWorkspaceShellContractTests(SimpleTestCase):
    def _source(self, relative_path: str) -> str:
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_root_template_renders_child_workspace_scripts(self):
        source = self._source("templates/index.html")

        self.assertIn("{% block scripts %}", source)
        self.assertIn("{% endblock scripts %}", source)
        self.assertLess(source.index("{% block scripts %}"), source.index("</body>"))

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
