from pathlib import Path

from django.test import SimpleTestCase
from django.urls import resolve


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Hr02WorkspaceV2ContractTests(SimpleTestCase):
    def _source(self, relative):
        return (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")

    def test_all_workspace_routes_resolve(self):
        for path in (
            "/hr/structure/organizations",
            "/hr/structure/relations",
            "/hr/structure/staffing-plans",
            "/hr/structure/post-catalogs",
            "/hr/structure/positions",
            "/hr/structure/history",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(resolve(path).func)

    def test_staffing_catalog_reorganization_and_position_actions_are_wired(self):
        workspace = self._source("frontend/static/hr/js/structure/workspace.js")
        positions = self._source("frontend/static/hr/js/structure/positions.js")
        template = self._source("frontend/templates/hr/structure/workspace.html")
        for endpoint in (
            "/api/v1/hr/structure/staffing-plans",
            "/api/v1/hr/structure/post-catalogs",
            "/api/v1/hr/structure/organization-changes",
            "/api/v1/hr/structure/organizations/options",
        ):
            self.assertIn(endpoint, workspace)
        for action in ("validate", "submit", "approve", "activate"):
            self.assertIn(f'["{action}"', workspace)
        for action in ("preview", "schedule", "execute"):
            self.assertIn(f'["{action}"', workspace)
        for action in ("freeze", "unfreeze", "close"):
            self.assertIn(f'data-position-action="{action}"', positions)
        self.assertIn("hr-position-pager", positions)
        self.assertIn('value="SKILLED_WORKER"', template)
        self.assertIn('value="SPECIAL"', template)
        self.assertNotIn('value="WORKER"', template)

    def test_operational_writers_are_post_only(self):
        source = self._source("backend/hr_structure/api/views.py")
        for function_name in ("effective_runner_trigger", "projection_run"):
            marker = f"@require_POST\ndef {function_name}"
            self.assertIn(marker, source)

