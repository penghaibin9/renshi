from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr06V2WorkspaceContractTests(SimpleTestCase):
    def setUp(self):
        root = Path(settings.BASE_DIR)
        self.center = (root / "hr_changes/templates/hr_changes/change_center.html").read_text(encoding="utf-8")
        self.new = (root / "hr_changes/templates/hr_changes/change_new.html").read_text(encoding="utf-8")
        self.nav = (root / "hr_changes/templates/hr_changes/components/v2_nav.html").read_text(encoding="utf-8")
        self.script = (root / "static/hr/js/pages/hr06-change-new.js").read_text(encoding="utf-8")
        self.css = (root / "static/hr/css/hr06-changes-v2.css").read_text(encoding="utf-8")

    def test_center_and_create_use_shared_v2_shell(self):
        for content in (self.center, self.new):
            self.assertIn('{% extends "index.html" %}', content)
            self.assertIn("hr-v2-page hr06-page", content)
            self.assertIn("hr06-changes-v2.css", content)
        self.assertNotIn("<!DOCTYPE html>", self.center)
        self.assertNotIn("<!DOCTYPE html>", self.new)
        self.assertNotIn("<style>", self.center)
        self.assertNotIn("<style>", self.new)

    def test_navigation_keeps_all_existing_hr06_workspaces(self):
        for route_name in (
            "hr06-change-center",
            "hr06-change-new",
            "hr06-changes-future-page",
            "hr06-transfers",
            "hr06-job-identity",
            "hr06-secondments",
            "hr06-ledger",
        ):
            self.assertIn(route_name, self.nav)

    def test_create_flow_uses_canonical_authorities_and_draft_semantics(self):
        self.assertIn("/api/v1/hr/changes/bootstrap", self.script)
        self.assertIn("/api/v1/hr/staff", self.script)
        self.assertIn("/api/v1/hr/changes", self.script)
        self.assertNotIn("/api/hr/v1/", self.script)
        self.assertIn("staffMasterId: state.selectedStaff.staff_id", self.script)
        self.assertIn("requestedEffectiveAt: effectiveAt.value", self.script)
        self.assertIn("proposals: []", self.script)
        self.assertIn("创建异动草稿", self.new)
        self.assertIn("DRAFT 草稿", self.new)
        self.assertNotIn("待接入 HR03 人员选择器", self.new)

    def test_create_page_never_uses_fake_submit_link_or_raw_staff_uuid_input(self):
        self.assertIn('id="hr06-create-draft"', self.new)
        self.assertIn('id="hr06-staff-keyword"', self.new)
        self.assertNotIn('href="/hr/changes/">提交</a>', self.new)
        self.assertNotIn("人员 UUID", self.new)
        self.assertNotIn("staff_master_id", self.new)

    def test_center_preserves_server_side_truthful_read_model(self):
        for token in ("stats.myTodos", "stats.underApproval", "stats.waitingEffective", "stats.effectiveThisMonth", "stats.risks"):
            self.assertIn(token, self.center)
        self.assertIn("it.statusLabel", self.center)
        self.assertIn("it.actionLabel", self.center)
        self.assertIn("创建草稿不等于提交审批", self.center)

    def test_module_css_stays_responsive_without_hiding_core_content(self):
        self.assertIn("@media (max-width: 720px)", self.css)
        self.assertNotIn("display: none", self.css)
