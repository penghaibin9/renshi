from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr02V2WorkspaceContractTests(SimpleTestCase):
    """Keep HR02 on the shared V2 shell without changing its business contract."""

    TEMPLATE_PATHS = (
        "templates/hr/structure/organizations.html",
        "templates/hr/structure/workspace.html",
        "templates/hr/structure/positions.html",
    )
    ROUTES = (
        "/hr/structure/organizations",
        "/hr/structure/relations",
        "/hr/structure/staffing-plans",
        "/hr/structure/post-catalogs",
        "/hr/structure/positions",
        "/hr/structure/history",
    )

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_all_hr02_surfaces_mount_the_shared_v2_shell(self):
        for relative_path in self.TEMPLATE_PATHS:
            with self.subTest(template=relative_path):
                source = self._source(relative_path)
                self.assertIn("hr/css/hr-v2.css", source)
                self.assertIn('data-module="HR02"', source)
                self.assertIn("hr-v2-mobile-section-switcher", source)
                self.assertIn("hr02-nav", source)

    def test_all_six_existing_hr02_routes_remain_visible_in_each_workspace(self):
        for relative_path in self.TEMPLATE_PATHS:
            source = self._source(relative_path)
            for route in self.ROUTES:
                with self.subTest(template=relative_path, route=route):
                    self.assertIn(f'href="{route}"', source)

    def test_interaction_dom_contracts_are_preserved(self):
        organizations = self._source("templates/hr/structure/organizations.html")
        positions = self._source("templates/hr/structure/positions.html")
        workspace = self._source("templates/hr/structure/workspace.html")

        for token in ("hr-org-search", "hr-org-tree", "hr-org-detail"):
            self.assertIn(f'id="{token}"', organizations)
        for token in ("hr-position-summary", "hr-position-table"):
            self.assertIn(f'id="{token}"', positions)
        for token in ("hr02-relation-form", "hr02-list", "hr02-search", "hr02-refresh"):
            self.assertIn(token, workspace)

    def test_hr02_specific_css_stays_flat(self):
        css = self._source("static/hr/css/hr02-workspace.css").lower()
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)
        self.assertNotIn("backdrop-filter", css)
