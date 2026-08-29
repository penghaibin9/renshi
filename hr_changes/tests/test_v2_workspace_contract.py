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
        self.identity = self.templates["job_identity.html"]
        self.nav = (template_root / "components/v2_nav.html").read_text(encoding="utf-8")
        self.script = (root / "static/hr/js/pages/hr06-change-new.js").read_text(encoding="utf-8")
        self.identity_script = (root / "static/hr/js/pages/hr06-identity.js").read_text(encoding="utf-8")
        self.temporary_script = (root / "static/hr/js/pages/hr06-temporary.js").read_text(encoding="utf-8")
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

    def test_create_flow_uses_canonical_authorities_and_transfer_service(self):
        for path in (
            "/api/v1/hr/changes/bootstrap",
            "/api/v1/hr/staff",
            "/api/v1/hr/structure/organizations/bootstrap",
            "/api/v1/hr/structure/organizations/tree",
            "/api/v1/hr/structure/positions",
            "/api/v1/hr/changes/transfers",
        ):
            self.assertIn(path, self.script)
        self.assertIn("/profile", self.script)
        self.assertNotIn("/api/hr/v1/", self.script)
        self.assertIn("staffMasterId: state.selectedStaff.staff_id", self.script)
        self.assertIn("requestedEffectiveAt: effectiveAt.value", self.script)
        self.assertNotIn("proposals: []", self.script)
        self.assertIn("TRANSFER_ACTIONS", self.script)
        self.assertIn('id="hr06-target-org"', self.new)
        self.assertIn('id="hr06-target-position"', self.new)
        self.assertIn("TransferService", self.new)
        self.assertIn("DRAFT 草稿", self.new)

    def test_identity_builder_only_opens_authority_proven_actions(self):
        self.assertIn("hr06-identity.js", self.identity)
        self.assertIn('id="hr06-identity-staff-keyword"', self.identity)
        self.assertIn('id="hr06-identity-action"', self.identity)
        self.assertIn('id="hr06-identity-target-fields"', self.identity)
        self.assertIn('id="hr06-identity-create"', self.identity)
        self.assertIn("人员类别、用工性质、直属上级、主岗切换、新增/结束兼岗", self.identity)
        self.assertIn("岗位类别变更、工作地点变更", self.identity)
        self.assertIn("Hr06ApplySupportProvider", self.identity)
        self.assertIn('"EMPLOYEE_CATEGORY_CHANGE"', self.identity_script)
        self.assertIn('"EMPLOYMENT_TYPE_CHANGE"', self.identity_script)
        for action_code in (
            "MANAGER_CHANGE",
            "PRIMARY_ASSIGNMENT_SWITCH",
            "ADD_SECONDARY_ASSIGNMENT",
            "END_SECONDARY_ASSIGNMENT",
        ):
            self.assertIn(f'"{action_code}"', self.identity_script)
        self.assertIn("SUPPORTED_IDENTITY_ACTIONS", self.identity_script)
        self.assertIn("identityOptions", self.identity_script)
        self.assertIn("proposed_value_ref", self.identity_script)
        self.assertIn("/api/v1/hr/changes/identity-changes", self.identity_script)
        self.assertIn("/api/v1/hr/staff", self.identity_script)
        self.assertIn("/profile", self.identity_script)
        self.assertIn("/assignments", self.identity_script)
        self.assertIn("/api/v1/hr/structure/organizations/bootstrap", self.identity_script)
        self.assertIn("/api/v1/hr/structure/positions", self.identity_script)
        self.assertIn("body.sourceAssignmentId", self.identity_script)
        self.assertNotIn("/api/hr/v1/", self.identity_script)

    def test_temporary_builder_uses_authorities_and_dedicated_writer(self):
        secondments = self.templates["secondments.html"]
        self.assertIn("hr06-temporary.js", secondments)
        for element_id in (
            "hr06-temporary-staff-keyword",
            "hr06-temporary-action",
            "hr06-temporary-reason",
            "hr06-temporary-target-org",
            "hr06-temporary-effective-at",
            "hr06-temporary-return-at",
            "hr06-temporary-create",
        ):
            self.assertIn(f'id="{element_id}"', secondments)
        for path in (
            "/api/v1/hr/changes/bootstrap",
            "/api/v1/hr/staff",
            "/api/v1/hr/structure/organizations/bootstrap",
            "/api/v1/hr/structure/organizations/tree",
            "/api/v1/hr/changes/temporary",
        ):
            self.assertIn(path, self.temporary_script)
        self.assertIn("staffMasterId: state.selectedStaff.staff_id", self.temporary_script)
        self.assertIn('sourcePolicy: "KEEP_ACTIVE"', self.temporary_script)
        self.assertIn("expectedReturnAt: returnAt.value", self.temporary_script)
        self.assertNotIn("/api/hr/v1/", self.temporary_script)
        self.assertNotIn('name="staffMasterId"', secondments)
        self.assertNotIn('name="targetOrgId"', secondments)

    def test_create_pages_never_use_fake_submit_links_or_raw_identity_ids(self):
        self.assertIn('id="hr06-create-draft"', self.new)
        self.assertIn('id="hr06-staff-keyword"', self.new)
        self.assertNotIn('href="/hr/changes/">提交</a>', self.new)
        self.assertNotIn('id="hr06-staff-id"', self.new)
        self.assertNotIn('name="staffMasterId"', self.new)
        self.assertNotIn('name="targetOrgId"', self.new)
        self.assertNotIn('name="targetPositionId"', self.new)
        self.assertNotIn("待接入 HR03 人员选择器", self.new)
        self.assertNotIn('name="staffMasterId"', self.identity)
        self.assertNotIn('name="staffCategoryCode"', self.identity)
        self.assertNotIn('name="relationshipType"', self.identity)

    def test_transfer_types_do_not_create_incomplete_generic_drafts(self):
        self.assertIn('"ORG_TRANSFER"', self.script)
        self.assertIn('"POSITION_TRANSFER"', self.script)
        self.assertIn('"ORG_POSITION_TRANSFER"', self.script)
        self.assertIn("item.enabled && TRANSFER_ACTIONS.has(item.code)", self.script)
        self.assertIn("未创建任何草稿", self.script)
        self.assertIn("服务端生成受管字段 proposals", self.new)

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
        self.assertNotIn("default:case.sourcePosition.code", detail)
        self.assertNotIn("default:case.targetPosition.code", detail)
        self.assertIn("blockers", preview)
        self.assertIn("warnings", preview)
        self.assertIn("requested_effective_at", self.templates["future_changes.html"])
        self.assertIn("it.statusLabel", self.templates["transfers.html"])
        self.assertIn("it.statusLabel", self.identity)
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
        self.assertIn(".hr06-capability-grid", self.css)
        self.assertNotIn("display: none", self.css)
