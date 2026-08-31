from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr03V2WorkspaceContractTests(SimpleTestCase):
    """Keep every HR03 browser surface in one product shell and preserve real contracts."""

    ROSTER_TEMPLATE = "hr_staff/templates/hr_staff/staff_list.html"
    PROFILE_TEMPLATE = "hr_staff/templates/hr_staff/profile.html"
    ASSIGNMENTS_TEMPLATE = "hr_staff/templates/hr_staff/assignment_history.html"
    BACKGROUNDS_TEMPLATE = "hr_staff/templates/hr_staff/background_facts.html"
    MATERIALS_TEMPLATE = "hr_staff/templates/hr_staff/materials.html"
    CORRECTIONS_TEMPLATE = "hr_staff/templates/hr_staff/corrections.html"
    DATA_QUALITY_TEMPLATE = "hr_staff/templates/hr_staff/data_quality.html"
    ERROR_TEMPLATE = "hr_staff/templates/hr_staff/error.html"

    WORKSPACE_TEMPLATES = (
        ROSTER_TEMPLATE,
        PROFILE_TEMPLATE,
        ASSIGNMENTS_TEMPLATE,
        BACKGROUNDS_TEMPLATE,
        MATERIALS_TEMPLATE,
        CORRECTIONS_TEMPLATE,
        DATA_QUALITY_TEMPLATE,
        ERROR_TEMPLATE,
    )

    CSS_PATHS = (
        "static/hr/css/hr03-staff.css",
        "static/hr/css/hr03-profile.css",
        "static/hr/css/hr03-history.css",
        "static/hr/css/hr03-records.css",
    )

    def _source(self, relative_path):
        if relative_path.startswith(("templates/", "static/")):
            root = Path(settings.FRONTEND_DIR)
        elif relative_path.startswith("scripts/"):
            root = Path(settings.REPO_ROOT)
        else:
            root = Path(settings.BACKEND_DIR)
        return (root / relative_path).read_text(encoding="utf-8")

    def test_all_hr03_surfaces_use_shared_horilla_v2_shell(self):
        for relative_path in self.WORKSPACE_TEMPLATES:
            with self.subTest(template=relative_path):
                source = self._source(relative_path)
                self.assertIn('{% extends "index.html" %}', source)
                self.assertNotIn("<!DOCTYPE html>", source)
                self.assertIn("hr/css/hr-v2.css", source)
                self.assertIn('data-module="HR03"', source)
                self.assertIn("hr-v2-mobile-section-switcher", source)

    def test_real_roster_actions_and_dom_ids_are_preserved(self):
        source = self._source(self.ROSTER_TEMPLATE)
        for token in (
            'id="keyword"',
            'id="status"',
            'id="category"',
            'id="searchBtn"',
            'id="rows"',
            'id="prev"',
            'id="next"',
            'id="importToggle"',
            'id="importFile"',
            'id="importValidate"',
            'id="importCommit"',
            'id="exportCurrent"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_roster_api_and_import_export_contracts_remain_visible(self):
        source = self._source(self.ROSTER_TEMPLATE)
        for endpoint in (
            "/api/hr/v1/staff?",
            "/api/hr/v1/staff/export",
            "/api/hr/v1/staff/import",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, source)
        self.assertIn("X-CSRFToken", source)
        self.assertIn("/hr/staff/data-quality/", source)
        self.assertIn("/hr/onboarding/", source)

    def test_profile_boot_reads_explicit_root_asof_and_real_child_routes(self):
        source = self._source(self.PROFILE_TEMPLATE)
        self.assertIn('data-as-of="{{ as_of }}"', source)
        self.assertIn("root.dataset.asOf", source)
        self.assertNotIn('getElementById("asof")', source)
        self.assertIn("/api/hr/v1/staff/${encodeURIComponent(staffId)}/profile", source)
        for suffix in ("/assignments", "/backgrounds", "/materials", "/corrections"):
            self.assertIn(suffix, source)
        self.assertIn("Profile bootstrap 不返回完整资格事实", source)
        self.assertIn("bootstrap 不返回高敏明文", source)

    def test_assignment_and_background_authority_reads_remain_real(self):
        assignments = self._source(self.ASSIGNMENTS_TEMPLATE)
        self.assertIn("/timeline", assignments)
        self.assertIn('data-section="assignments"', assignments)
        self.assertIn("暂无任职履历", assignments)

        backgrounds = self._source(self.BACKGROUNDS_TEMPLATE)
        self.assertIn("/backgrounds", backgrounds)
        self.assertIn('data-section="backgrounds"', backgrounds)
        for kind in ("edu", "degree", "work", "cred", "honor"):
            self.assertIn(f'data-kind="{kind}"', backgrounds)

    def test_material_download_stays_ticketed_and_never_exposes_media_url(self):
        source = self._source(self.MATERIALS_TEMPLATE)
        self.assertIn("/materials/${encodeURIComponent(materialId)}/download-ticket", source)
        self.assertIn("/download/${encodeURIComponent(ticket)}", source)
        self.assertIn("X-CSRFToken", source)
        self.assertIn("请填写查看用途", source)
        self.assertNotIn("/media/", source)

    def test_correction_ui_keeps_state_machine_transitions_and_csrf(self):
        source = self._source(self.CORRECTIONS_TEMPLATE)
        self.assertIn("/corrections/list", source)
        self.assertIn("/api/hr/v1/corrections/${encodeURIComponent(caseId)}/${action}", source)
        self.assertIn("X-CSRFToken", source)
        for action in (
            '"submit"',
            '"review"',
            '"return"',
            '"resubmit"',
            '"approve"',
            '"reject"',
            '"cancel"',
            '"apply"',
        ):
            with self.subTest(action=action):
                self.assertIn(action, source)

    def test_data_quality_does_not_treat_not_run_or_failure_as_clean(self):
        source = self._source(self.DATA_QUALITY_TEMPLATE)
        self.assertIn('id="scanForm"', source)
        self.assertIn('id="asOf"', source)
        self.assertIn("/api/hr/v1/staff/data-quality-scan", source)
        self.assertIn("尚未执行扫描", source)
        self.assertIn("本次扫描没有返回数据质量异常", source)
        self.assertIn('data-state="error"', source)

    def test_access_error_surface_stays_fail_closed_inside_v2_shell(self):
        source = self._source(self.ERROR_TEMPLATE)
        self.assertIn("当前工作区不可访问", source)
        self.assertIn("fail-closed", source)
        self.assertIn("{{ error_code", source)
        self.assertIn("{{ error_message", source)

    def test_views_keep_required_staff_and_asof_context(self):
        views = self._source("hr_staff/views.py")
        self.assertIn('"staff_id": str(staff_id)', views)
        self.assertIn('"as_of": context.as_of.isoformat() if context.as_of else ""', views)
        self.assertIn('{"staff_id": str(staff_id), "as_of": context.as_of.isoformat()}', views)
        self.assertIn('"hr_staff/error.html"', views)
        self.assertIn("status=403", views)

    def test_real_browser_gate_traverses_profile_and_four_child_workspaces(self):
        browser = self._source("scripts/hr_real_browser_click.py")
        self.assertIn("HR03 roster did not mount the V2 workspace shell", browser)
        self.assertIn("HR03 roster rendered no real staff profile link", browser)
        for child in ("assignments", "backgrounds", "materials", "corrections"):
            with self.subTest(child=child):
                self.assertIn(f'("{child}", "{child}")', browser)
        self.assertIn("staff-child-workspace-click", browser)
        self.assertIn("profile-real-runtime-click.png", browser)

    def test_profile_outer_shell_is_flat_not_card_inside_card(self):
        css = self._source("static/hr/css/hr03-profile.css")
        self.assertIn(".hr03-page > section.hr-v2-panel", css)
        self.assertIn("box-shadow: none", css)
        self.assertIn("background: transparent", css)

    def test_hr03_css_stays_on_flat_v2_foundation(self):
        css = "\n".join(self._source(path).lower() for path in self.CSS_PATHS)
        self.assertNotIn("linear-gradient", css)
        self.assertNotIn("radial-gradient", css)
        self.assertNotIn("backdrop-filter", css)
