"""Real Chromium acceptance for HR06 V2 personnel-change workspaces.

The suite seeds only technical identity plus HR03/HR02 authority facts and
HR06 action/reason configuration needed to exercise real specialized create
flows. It never seeds a personnel-change result row: DRAFT cases must be
created by the production browser/API paths themselves.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
class Hr06VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    ROUTES = (
        ("center", "/hr/changes/", None, None),
        ("new", "/hr/changes/new", "hr06-bootstrap-state", "正在读取 HR06"),
        ("future", "/hr/changes/future", None, None),
        ("transfers", "/hr/changes/transfers", None, None),
        ("identity", "/hr/changes/job-identity", "hr06-identity-bootstrap-state", "正在读取 HR06"),
        ("secondments", "/hr/changes/secondments", "hr06-temporary-bootstrap-state", "正在读取 HR06"),
        ("ledger", "/hr/changes/ledger", None, None),
    )

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_changes.tests.factories import make_action, make_org, make_position, make_reason
        from hr_staff.constants import AssignmentType
        from hr_staff.services.assignment_service import AssignmentService
        from hr_staff.services.employment_service import EmploymentService
        from hr_staff.tests.factories import make_person, make_staff
        from hr_structure.models import HrOrganizationVersion

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR06 视觉验收学校",
            hq=True,
            address="长沙市视觉验收路 6 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr06-visual.png", b"hr06-visual", content_type="image/png"),
        )
        self.user = User.objects.create_superuser(
            username="hr06-visual-auditor",
            email="hr06-visual@example.invalid",
            password="hr06-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR06",
            employee_last_name="视觉验收员",
            email="hr06-employee@example.invalid",
            phone="13800000006",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        if work_info.company_id_id != self.company.pk:
            work_info.company_id = self.company
            work_info.save(update_fields=["company_id"])

        person = make_person(self.company.pk, "真实创建测试教师")
        self.staff = make_staff(self.company.pk, person, "HR06-CLICK-001")
        self.root_org = make_org(
            self.company.pk,
            "VISUAL-SCHOOL",
            "跃科视觉验收学校",
            date(2020, 1, 1),
            org_type="SCHOOL",
        )
        self.source_org = make_org(
            self.company.pk,
            "VISUAL-SOURCE",
            "视觉原学院",
            date(2020, 1, 1),
        )
        self.target_org = make_org(
            self.company.pk,
            "VISUAL-TARGET",
            "视觉目标学院",
            date(2020, 1, 1),
        )
        HrOrganizationVersion.objects.filter(
            organization_id__in=(self.source_org, self.target_org),
        ).update(parent_organization_id=self.root_org)
        self.source_position = make_position(
            self.company.pk,
            self.source_org,
            "VISUAL-SOURCE-POSITION",
        )
        relationship = EmploymentService(self.company.pk).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        self.source_assignment = AssignmentService(self.company.pk).create_assignment(
            employment_relationship_id=relationship,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.source_org,
            position_id=self.source_position,
            post_catalog_id=self.source_position.post_catalog_version_id,
            source_business_type="MIGRATION_VERIFIED",
        )
        self.secondary_position = make_position(
            self.company.pk,
            self.target_org,
            "VISUAL-SECONDARY-POSITION",
        )
        self.secondary_assignment = AssignmentService(self.company.pk).create_assignment(
            employment_relationship_id=relationship,
            assignment_type=AssignmentType.CONCURRENT,
            effective_from=date(2025, 9, 1),
            organization_id=self.target_org,
            position_id=self.secondary_position,
            post_catalog_id=self.secondary_position.post_catalog_version_id,
            fte=Decimal("0.20"),
            source_business_type="MIGRATION_VERIFIED",
        )
        self.action = make_action(
            self.company.pk,
            code="ORG_TRANSFER",
            name="组织调动",
            enabled=True,
        )
        self.reason = make_reason(
            self.company.pk,
            action_code="ORG_TRANSFER",
            code="WORK_NEED",
            name="工作需要",
        )
        self.identity_action = make_action(
            self.company.pk,
            code="EMPLOYEE_CATEGORY_CHANGE",
            name="人员类别变更",
            enabled=True,
        )
        self.identity_reason = make_reason(
            self.company.pk,
            action_code="EMPLOYEE_CATEGORY_CHANGE",
            code="CATEGORY_ADJUST",
            name="岗位职责调整",
        )
        self.employment_action = make_action(
            self.company.pk,
            code="EMPLOYMENT_TYPE_CHANGE",
            name="用工性质变更",
            enabled=True,
        )
        make_reason(
            self.company.pk,
            action_code="EMPLOYMENT_TYPE_CHANGE",
            code="EMPLOYMENT_ADJUST",
            name="聘用关系调整",
        )
        self.temporary_action = make_action(
            self.company.pk,
            code="TEMPORARY_SECONDMENT",
            name="借调",
            enabled=True,
        )
        self.temporary_reason = make_reason(
            self.company.pk,
            action_code="TEMPORARY_SECONDMENT",
            code="TEMPORARY_WORK_NEED",
            name="临时工作需要",
        )
        self.end_secondary_action = make_action(
            self.company.pk,
            code="END_SECONDARY_ASSIGNMENT",
            name="结束兼岗",
            enabled=True,
        )
        self.end_secondary_reason = make_reason(
            self.company.pk,
            action_code="END_SECONDARY_ASSIGNMENT",
            code="SECONDARY_DUTY_END",
            name="兼岗任务结束",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")) / "HR06-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _browser_context(self, browser, *, viewport=None):
        context = browser.new_context(
            viewport=viewport or {"width": 1440, "height": 1000},
            device_scale_factor=1,
        )
        context.add_cookies([
            {
                "name": settings.SESSION_COOKIE_NAME,
                "value": self.session_cookie,
                "url": self.live_server_url,
            }
        ])
        return context

    @staticmethod
    def _record_console(page, page_errors, console_errors):
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

    def test_capture_primary_hr06_workspaces_desktop_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        page_errors: list[str] = []
        console_errors: list[str] = []
        api_failures: list[str] = []
        static_failures: list[str] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                self._record_console(page, page_errors, console_errors)

                def record_response(response):
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/" in response.url and response.status >= 400:
                        static_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)
                for section, route, settle_id, loading_text in self.ROUTES:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response, route)
                    self.assertEqual(response.status, 200, route)
                    self.assertEqual(
                        page.locator(f'[data-module="HR06"][data-section="{section}"]').count(),
                        1,
                        route,
                    )
                    self.assertEqual(page.locator(".hr06-nav a").count(), 7, route)
                    if settle_id and loading_text:
                        page.wait_for_function(
                            """([id, text]) => {
                              const host = document.getElementById(id);
                              return host && !host.textContent.includes(text);
                            }""",
                            arg=[settle_id, loading_text],
                            timeout=8000,
                        )
                    page.screenshot(path=str(self.out_dir / f"desktop-{section}.png"), full_page=True)

                page.set_viewport_size({"width": 390, "height": 844})
                for section, route, settle_id, loading_text in self.ROUTES:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response, route)
                    self.assertEqual(response.status, 200, route)
                    self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1, route)
                    self.assertEqual(page.locator(".hr06-nav a").count(), 7, route)
                    if settle_id and loading_text:
                        page.wait_for_function(
                            """([id, text]) => {
                              const host = document.getElementById(id);
                              return host && !host.textContent.includes(text);
                            }""",
                            arg=[settle_id, loading_text],
                            timeout=8000,
                        )
                    page.screenshot(path=str(self.out_dir / f"mobile-{section}.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR06 page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR06 console errors: " + " | ".join(console_errors))
        self.assertEqual(api_failures, [], "HR06 canonical API failures: " + " | ".join(api_failures))
        self.assertEqual(static_failures, [], "HR06 static resource failures: " + " | ".join(static_failures))

    def test_real_browser_creates_transfer_draft_through_authorities(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        api_failures: list[str] = []
        page_errors: list[str] = []
        console_errors: list[str] = []
        effective_date = (date.today() + timedelta(days=30)).isoformat()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                self._record_console(page, page_errors, console_errors)

                def record_response(response):
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)
                response = page.goto(self.live_server_url + "/hr/changes/new", wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-bootstrap-state');
                      return host && !host.textContent.includes('正在读取 HR06');
                    }""",
                    timeout=8000,
                )

                page.fill("#hr06-staff-keyword", self.staff.staff_no)
                page.click("#hr06-search-staff")
                page.wait_for_selector(".hr06-staff-option", timeout=8000)
                page.locator(".hr06-staff-option").first.click()
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-selected-staff');
                      return host && !host.textContent.includes('正在读取 HR03');
                    }""",
                    timeout=8000,
                )
                page.select_option("#hr06-action", str(self.action.id))
                page.wait_for_function(
                    """() => {
                      const node = document.getElementById('hr06-reason');
                      return node && !node.disabled && node.options.length > 1;
                    }""",
                    timeout=5000,
                )
                page.select_option("#hr06-reason", str(self.reason.id))
                page.wait_for_function(
                    """() => {
                      const node = document.getElementById('hr06-target-org');
                      return node && !node.disabled && node.options.length > 1;
                    }""",
                    timeout=8000,
                )
                page.select_option("#hr06-target-org", str(self.target_org.id))
                page.fill("#hr06-effective-at", effective_date)
                page.wait_for_function(
                    """() => !document.getElementById('hr06-create-draft').disabled""",
                    timeout=5000,
                )
                page.click("#hr06-create-draft")
                page.wait_for_url(re.compile(r"/hr/changes/[0-9a-f-]{36}$"), timeout=10000)
                self.assertEqual(page.locator('[data-module="HR06"][data-section="detail"]').count(), 1)
                self.assertIn("草稿", page.locator("body").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-created-transfer-draft.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        from hr_changes.models import HrPersonnelChangeCase

        cases = list(HrPersonnelChangeCase.objects.filter(tenant_id=self.company.pk))
        self.assertEqual(len(cases), 1)
        created = cases[0]
        self.assertEqual(created.status, "DRAFT")
        self.assertEqual(created.staff_master_id_id, self.staff.id)
        self.assertEqual(created.action_id_id, self.action.id)
        self.assertEqual(created.reason_id_id, self.reason.id)
        self.assertEqual(created.target_org_id_id, self.target_org.id)
        self.assertEqual(created.requested_effective_at.isoformat(), effective_date)
        self.assertEqual(created.proposals.filter(field_code="organization").count(), 1)
        self.assertEqual(api_failures, [], "HR06 transfer API failures: " + " | ".join(api_failures))
        self.assertEqual(page_errors, [], "HR06 transfer page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR06 transfer console errors: " + " | ".join(console_errors))

    def test_real_browser_creates_controlled_identity_category_draft(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        api_failures: list[str] = []
        page_errors: list[str] = []
        console_errors: list[str] = []
        effective_date = (date.today() + timedelta(days=30)).isoformat()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                self._record_console(page, page_errors, console_errors)

                def record_response(response):
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)
                response = page.goto(self.live_server_url + "/hr/changes/job-identity", wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-identity-bootstrap-state');
                      return host && !host.textContent.includes('正在读取 HR06');
                    }""",
                    timeout=8000,
                )
                page.fill("#hr06-identity-staff-keyword", self.staff.staff_no)
                page.click("#hr06-identity-search-staff")
                page.wait_for_selector(".hr06-staff-option", timeout=8000)
                page.locator(".hr06-staff-option").first.click()
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-identity-selected-staff');
                      return host && host.textContent.includes('当前人员类别');
                    }""",
                    timeout=8000,
                )
                page.select_option("#hr06-identity-action", str(self.identity_action.id))
                page.wait_for_function(
                    """() => {
                      const node = document.getElementById('hr06-identity-reason');
                      return node && !node.disabled && node.options.length > 1;
                    }""",
                    timeout=5000,
                )
                page.select_option("#hr06-identity-reason", str(self.identity_reason.id))
                page.wait_for_selector("#hr06-identity-staff-category", timeout=5000)
                page.select_option("#hr06-identity-staff-category", "ADMIN")
                page.fill("#hr06-identity-effective-at", effective_date)
                page.wait_for_function(
                    """() => !document.getElementById('hr06-identity-create').disabled""",
                    timeout=5000,
                )
                page.click("#hr06-identity-create")
                page.wait_for_url(re.compile(r"/hr/changes/[0-9a-f-]{36}$"), timeout=10000)
                self.assertIn("草稿", page.locator("body").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-created-identity-category-draft.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        from hr_changes.models import HrPersonnelChangeCase

        cases = list(HrPersonnelChangeCase.objects.filter(tenant_id=self.company.pk))
        self.assertEqual(len(cases), 1)
        created = cases[0]
        self.assertEqual(created.status, "DRAFT")
        self.assertEqual(created.action_id_id, self.identity_action.id)
        proposal = created.proposals.get(field_code="staff_category_code")
        self.assertEqual(proposal.proposed_value_ref, "ADMIN")
        self.assertEqual(proposal.proposed_value_display, "行政管理")
        self.assertEqual(api_failures, [], "HR06 identity API failures: " + " | ".join(api_failures))
        self.assertEqual(page_errors, [], "HR06 identity page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR06 identity console errors: " + " | ".join(console_errors))

    def test_real_browser_creates_temporary_draft_through_authorities(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        api_failures: list[str] = []
        page_errors: list[str] = []
        console_errors: list[str] = []
        effective_date = (date.today() + timedelta(days=30)).isoformat()
        return_date = (date.today() + timedelta(days=180)).isoformat()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                self._record_console(page, page_errors, console_errors)

                def record_response(response):
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)
                response = page.goto(self.live_server_url + "/hr/changes/secondments", wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-temporary-bootstrap-state');
                      return host && !host.textContent.includes('正在读取 HR06');
                    }""",
                    timeout=8000,
                )
                self.assertFalse(
                    page.locator("#hr06-temporary-action").is_disabled(),
                    "temporary bootstrap did not enable actions: "
                    + page.locator("#hr06-temporary-bootstrap-state").inner_text()
                    + " | API: "
                    + " | ".join(api_failures)
                    + " | page: "
                    + " | ".join(page_errors)
                    + " | console: "
                    + " | ".join(console_errors),
                )
                page.fill("#hr06-temporary-staff-keyword", self.staff.staff_no)
                page.click("#hr06-temporary-search-staff")
                page.wait_for_selector(".hr06-staff-option", timeout=8000)
                page.locator(".hr06-staff-option").first.click()
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-temporary-selected-staff');
                      return host && !host.textContent.includes('正在读取 HR03');
                    }""",
                    timeout=8000,
                )
                page.select_option("#hr06-temporary-action", str(self.temporary_action.id))
                page.wait_for_function(
                    """() => {
                      const node = document.getElementById('hr06-temporary-reason');
                      return node && !node.disabled && node.options.length > 1;
                    }""",
                    timeout=5000,
                )
                page.select_option("#hr06-temporary-reason", str(self.temporary_reason.id))
                page.select_option("#hr06-temporary-target-org", str(self.target_org.id))
                page.fill("#hr06-temporary-effective-at", effective_date)
                page.fill("#hr06-temporary-return-at", return_date)
                page.wait_for_function(
                    """() => !document.getElementById('hr06-temporary-create').disabled""",
                    timeout=5000,
                )
                page.click("#hr06-temporary-create")
                page.wait_for_url(re.compile(r"/hr/changes/[0-9a-f-]{36}$"), timeout=10000)
                self.assertIn("草稿", page.locator("body").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-created-temporary-draft.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        from hr_changes.models import HrPersonnelChangeCase

        cases = list(HrPersonnelChangeCase.objects.filter(tenant_id=self.company.pk))
        self.assertEqual(len(cases), 1)
        created = cases[0]
        self.assertEqual(created.status, "DRAFT")
        self.assertEqual(created.staff_master_id_id, self.staff.id)
        self.assertEqual(created.action_id_id, self.temporary_action.id)
        self.assertEqual(created.reason_id_id, self.temporary_reason.id)
        self.assertEqual(created.target_org_id_id, self.target_org.id)
        self.assertEqual(created.requested_effective_at.isoformat(), effective_date)
        proposals = {
            proposal.field_code: proposal.proposed_value_ref
            for proposal in created.proposals.all()
        }
        self.assertEqual(proposals["organization"], str(self.target_org.id))
        self.assertEqual(proposals["expected_return_at"], return_date)
        self.assertEqual(proposals["source_policy"], "KEEP_ACTIVE")
        self.assertEqual(api_failures, [], "HR06 temporary API failures: " + " | ".join(api_failures))
        self.assertEqual(page_errors, [], "HR06 temporary page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR06 temporary console errors: " + " | ".join(console_errors))

    def test_real_browser_selects_exact_concurrent_assignment_for_end_draft(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        api_failures: list[str] = []
        page_errors: list[str] = []
        console_errors: list[str] = []
        effective_date = (date.today() + timedelta(days=30)).isoformat()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._browser_context(browser)
                page = context.new_page()
                self._record_console(page, page_errors, console_errors)

                def record_response(response):
                    if "/api/v1/hr/" in response.url and response.status >= 400:
                        api_failures.append(f"{response.status} {response.url}")

                page.on("response", record_response)
                response = page.goto(self.live_server_url + "/hr/changes/job-identity", wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-identity-bootstrap-state');
                      return host && !host.textContent.includes('正在读取 HR06');
                    }""",
                    timeout=8000,
                )
                page.fill("#hr06-identity-staff-keyword", self.staff.staff_no)
                page.click("#hr06-identity-search-staff")
                page.wait_for_selector(".hr06-staff-option", timeout=8000)
                page.locator(".hr06-staff-option").first.click()
                page.wait_for_function(
                    """() => {
                      const host = document.getElementById('hr06-identity-selected-staff');
                      return host && host.textContent.includes('当前人员类别');
                    }""",
                    timeout=8000,
                )
                page.fill("#hr06-identity-effective-at", effective_date)
                page.select_option("#hr06-identity-action", str(self.end_secondary_action.id))
                page.wait_for_function(
                    """() => {
                      const node = document.getElementById('hr06-identity-reason');
                      return node && !node.disabled && node.options.length > 1;
                    }""",
                    timeout=5000,
                )
                page.select_option("#hr06-identity-reason", str(self.end_secondary_reason.id))
                page.wait_for_function(
                    """() => {
                      const node = document.getElementById('hr06-identity-source-assignment');
                      return node && !node.disabled && node.options.length > 1;
                    }""",
                    timeout=8000,
                )
                page.select_option("#hr06-identity-source-assignment", str(self.secondary_assignment.id))
                page.wait_for_function(
                    """() => !document.getElementById('hr06-identity-create').disabled""",
                    timeout=5000,
                )
                page.click("#hr06-identity-create")
                page.wait_for_url(re.compile(r"/hr/changes/[0-9a-f-]{36}$"), timeout=10000)
                self.assertIn("草稿", page.locator("body").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-created-end-secondary-draft.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        from hr_changes.models import HrPersonnelChangeCase

        cases = list(HrPersonnelChangeCase.objects.filter(tenant_id=self.company.pk))
        self.assertEqual(len(cases), 1)
        created = cases[0]
        self.assertEqual(created.status, "DRAFT")
        self.assertEqual(created.staff_master_id_id, self.staff.id)
        self.assertEqual(created.action_id_id, self.end_secondary_action.id)
        self.assertEqual(created.reason_id_id, self.end_secondary_reason.id)
        self.assertEqual(created.source_assignment_id_id, self.secondary_assignment.id)
        self.assertEqual(created.source_org_id_id, self.target_org.id)
        self.assertEqual(created.source_position_id_id, self.secondary_position.id)
        proposal = created.proposals.get(field_code="effective_to")
        self.assertEqual(proposal.proposed_value_ref, effective_date)
        self.assertEqual(api_failures, [], "HR06 end-secondary API failures: " + " | ".join(api_failures))
        self.assertEqual(page_errors, [], "HR06 end-secondary page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR06 end-secondary console errors: " + " | ".join(console_errors))
