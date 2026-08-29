from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr06V2WorkspaceContractTests(SimpleTestCase):
    def setUp(self):
        root = Path(settings.BASE_DIR)
        template_root = root / "hr_changes/templates/hr_changes"
        self.templates = {
            name: (template_root / name).read_text(encoding="utf-8")
            for name in (
                "change_center.html",
                "change_new.html",
                "change_detail.html",
                "change_preview.html",
                "future_changes.html",
                "transfers.html",
                "job_identity.html",
                "secondments.html",
                "ledger.html",
                "error.html",
            )
        }
        self.center = self.templates["change_center.html"]
        self.new = self.templates["change_new.html"]
        self.nav = (template_root / "components/v2_nav.html").read_text(encoding="utf-8")
        self.script = (root / "static/hr/js/pages/hr06-change-new.js").read_text(encoding="utf-8")
        self.css = (root / "static/hr/css/hr06-changes-v2.css").read_text(encoding="utf-8")

    def test_all_hr06_surfaces_use_shared_v2_shell(self):
        for name, content in self.templates.items():
            with self.subTest(name=name):
                self.assertIn('{% extends "index.html" %}', content)
                self.assertIn("hr-v2-page hr06-page", content)
                self.assertIn("hr06-changes-v2.css", content)
                self.assertNotIn("<!DOCTYPE html>", content)
                self.assertNotIn("<style>", content)

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
        self.assertNotIn('id="hr06-staff-id"', self.new)
        self.assertNotIn('name="staffMasterId"', self.new)
        self.assertNotIn("staff_master_id", self.new)

    def test_center_preserves_server_side_truthful_read_model(self):
        for token in (
            "stats.myTodos",
            "stats.underApproval",
            "stats.waitingEffective",
            "stats.effectiveThisMonth",
            "stats.risks",
        ):
            self.assertIn(token, self.center)
        self.assertIn("it.statusLabel", self.center)
        self.assertIn("it.actionLabel", self.center)
        self.assertIn("创建草稿不等于提交审批", self.center)

    def test_detail_preview_and_specialized_views_preserve_real_read_models(self):
        detail = self.templates["change_detail.html"]
        preview = self.templates["change_preview.html"]
        self.assertIn("case.proposals", detail)
        self.assertIn("case.timeline", detail)
        self.assertIn("case.downstream", detail)
        self.assertIn("blockers", preview)
        self.assertIn("warnings", preview)
        self.assertIn("requested_effective_at", self.templates["future_changes.html"])
        self.assertIn("it.statusLabel", self.templates["transfers.html"])
        self.assertIn("stats.overdue", self.templates["secondments.html"])
        self.assertIn("it.appliedAt", self.templates["ledger.html"])
        self.assertIn("error_code", self.templates["error.html"])
        self.assertIn("error_message", self.templates["error.html"])

    def test_specialized_pages_do_not_claim_approval_or_effect_from_navigation(self):
        for name in (
            "future_changes.html",
            "transfers.html",
            "job_identity.html",
            "secondments.html",
            "ledger.html",
        ):
            content = self.templates[name]
            self.assertNotIn(">提交审批</a>", content)
            self.assertNotIn(">正式生效</a>", content)
        self.assertIn("批准事实与正式生效事实保持分离", self.templates["future_changes.html"])

    def test_module_css_stays_responsive_without_hiding_core_content(self):
        self.assertIn("@media (max-width: 720px)", self.css)
        self.assertIn(".hr06-detail-grid", self.css)
        self.assertIn(".hr06-impact-item--blocker", self.css)
        self.assertNotIn("display: none", self.css)
