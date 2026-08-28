"""Real Chromium acceptance for the HR18 data governance V2 workspace."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.utils import timezone


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "visual audit is CI-explicit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-hr18-visual-media-"))
class Hr18VisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_data.models import (
            AsOfEvidenceSnapshot,
            DataQualityFinding,
            MetricDefinitionVersion,
            PopulationDefinitionVersion,
            SubmissionSnapshot,
        )

        User = get_user_model()
        self.company = Company.objects.create(
            company="跃科 HR18 视觉验收学校",
            hq=True,
            address="长沙市人事数据路 18 号",
            country="CN",
            state="Hunan",
            city="Changsha",
            zip="410000",
            icon=SimpleUploadedFile("hr18.png", b"hr18", content_type="image/png"),
        )
        self.user = User.objects.create_superuser(
            username="hr18-visual-auditor",
            email="hr18-visual@example.invalid",
            password="hr18-visual-only-password",
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR18",
            employee_last_name="数据验收员",
            email="hr18-employee@example.invalid",
            phone="13800000018",
            is_active=True,
        )
        work, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        if work.company_id_id != self.company.pk:
            work.company_id = self.company
            work.save(update_fields=["company_id"])

        tenant_id = self.company.pk
        PopulationDefinitionVersion.objects.create(
            tenant_id=tenant_id,
            population_code="ACTIVE_STAFF",
            name="在岗教职工",
            version_no=1,
            status="ACTIVE",
            root_domain="HR03",
            grain=PopulationDefinitionVersion.Grain.STAFF,
            source_domains=["HR03"],
            as_of_required=True,
        )
        MetricDefinitionVersion.objects.create(
            tenant_id=tenant_id,
            metric_code="HEADCOUNT",
            name="在岗人数",
            version_no=1,
            status="ACTIVE",
            value_type="INTEGER",
            unit="人",
            population_code="ACTIVE_STAFF",
            expression="COUNT",
            source_domains=["HR03"],
            as_of_required=True,
        )
        DataQualityFinding.objects.create(
            tenant_id=tenant_id,
            finding_no="DQ-HR18-001",
            rule_code="HR03_REQUIRED_FIELD",
            rule_version=1,
            source_domain="HR03",
            source_object_ref="staff:visual-001",
            finding_fingerprint="hr18-visual-critical-001",
            severity=DataQualityFinding.Severity.CRITICAL,
            details_json={"field": "staff_no"},
            status=DataQualityFinding.Status.OPEN,
            detected_at=timezone.now(),
        )
        AsOfEvidenceSnapshot.objects.create(
            tenant_id=tenant_id,
            evidence_no="ASOF-HR18-COMPLETE",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            status=AsOfEvidenceSnapshot.Status.COMPLETE,
            source_statuses_json={"HR03": "COMPLETE"},
            blocked_domains_json=[],
            provider_versions_json={"HR03": "visual-v1"},
            provider_evidence_hashes_json={"HR03": "a" * 64},
            evidence_hash="b" * 64,
        )
        AsOfEvidenceSnapshot.objects.create(
            tenant_id=tenant_id,
            evidence_no="ASOF-HR18-PARTIAL",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 7, 1),
            status=AsOfEvidenceSnapshot.Status.PARTIAL,
            source_statuses_json={"HR03": "PARTIAL"},
            blocked_domains_json=["HR03"],
            provider_versions_json={"HR03": "visual-v1"},
            provider_evidence_hashes_json={},
            evidence_hash="c" * 64,
        )
        SubmissionSnapshot.objects.create(
            tenant_id=tenant_id,
            submission_no="SUB-HR18-FAILED",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            scope_json={"tenant": tenant_id},
            payload_hash="d" * 64,
            status=SubmissionSnapshot.Status.DISPATCH_FAILED,
            dispatch_error="visual dispatch failure evidence",
        )
        SubmissionSnapshot.objects.create(
            tenant_id=tenant_id,
            submission_no="SUB-HR18-AWAITING",
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code="HEADCOUNT",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            scope_json={"tenant": tenant_id},
            payload_hash="e" * 64,
            status=SubmissionSnapshot.Status.SUBMITTED,
            submitted_at=timezone.now(),
            receipt_ref="",
        )

        client = Client()
        client.force_login(self.user)
        session = client.session
        session["selected_company"] = str(self.company.pk)
        session["otp_code_verified"] = True
        session.save()
        self.session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.out_dir = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "artifacts/hr-visual")) / "HR18-V2"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_capture_hr18_data_center_v2_desktop_routes_and_mobile(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright must be installed for HR visual audit") from exc

        routes = [
            "/hr/data/",
            "/hr/data/metrics/",
            "/hr/data/population/",
            "/hr/data/as-of/",
            "/hr/data/quality/",
            "/hr/data/exchange/",
            "/hr/data/submissions/",
            "/hr/data/corrections/",
        ]
        page_errors = []
        console_errors = []
        static_failures = []
        dashboard_requests = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
                context.add_cookies([
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": self.session_cookie,
                        "url": self.live_server_url,
                    }
                ])
                page = context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on(
                    "response",
                    lambda response: static_failures.append(f"{response.status} {response.url}")
                    if "/static/hr/" in response.url and response.status >= 400
                    else None,
                )
                page.on(
                    "request",
                    lambda request: dashboard_requests.append(request.url)
                    if "/api/v1/hr/data/dashboard/" in request.url
                    else None,
                )

                response = page.goto(self.live_server_url + routes[0], wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator("[data-module='HR18'].hr-v2-page").count(), 1)
                self.assertEqual(page.locator(".hr18-nav a").count(), 8)
                self.assertEqual(page.locator(".hr18-hero").count(), 0)
                self.assertEqual(page.locator("#hr18-kpis .hr18-kpi").count(), 6)
                page.wait_for_function(
                    """() => Array.from(document.querySelectorAll('#hr18-kpis .hr18-kpi b')).every((n) => n.textContent.trim() !== '—')""",
                    timeout=8000,
                )
                page.wait_for_function(
                    """() => document.querySelector('#hr18-priority')?.textContent.includes('1 个严重质量问题')""",
                    timeout=8000,
                )
                body_text = page.locator("body").inner_text()
                self.assertIn("1 个严重质量问题", body_text)
                self.assertIn("异步数据交换", body_text)
                self.assertIn("未接通", body_text)
                self.assertGreaterEqual(len(dashboard_requests), 1)

                styles = page.evaluate(
                    """() => Array.from(document.styleSheets).map((sheet) => sheet.href || '').filter(Boolean)"""
                )
                diag = (
                    f"styles={styles}; page_errors={page_errors}; "
                    f"console_errors={console_errors}; static_failures={static_failures}"
                )
                self.assertTrue(any("/hr/css/hr-v2.css" in item for item in styles), diag)
                self.assertTrue(any("/hr/css/hr18-data.css" in item for item in styles), diag)
                self.assertEqual(page_errors, [], diag)
                self.assertEqual(static_failures, [], diag)
                page.screenshot(path=str(self.out_dir / "desktop-overview.png"), full_page=True)

                for route in routes[1:]:
                    response = page.goto(self.live_server_url + route, wait_until="networkidle")
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status, 200, f"HR18 {route} returned HTTP {response.status}")
                    self.assertEqual(page.locator("[data-module='HR18'].hr-v2-page").count(), 1)
                    self.assertEqual(page.locator(".hr18-nav a").count(), 8)

                response = page.goto(self.live_server_url + "/hr/data/exchange/", wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                page.wait_for_function(
                    """() => document.querySelector('#hr18-boundary')?.textContent.includes('当前未接通')""",
                    timeout=8000,
                )
                self.assertIn("同步导出不会伪装成交换任务中心", page.locator("#hr18-boundary").inner_text())
                page.screenshot(path=str(self.out_dir / "desktop-exchange-unavailable.png"), full_page=True)

                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(self.live_server_url + routes[0], wait_until="networkidle")
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertEqual(page.locator(".hr-v2-mobile-section-switcher").count(), 1)
                self.assertEqual(page.locator("[data-module='HR18'].hr-v2-page").count(), 1)
                page.screenshot(path=str(self.out_dir / "mobile-overview.png"), full_page=True)
                context.close()
            finally:
                browser.close()

        self.assertEqual(page_errors, [], "HR18 browser page errors: " + " | ".join(page_errors))
        self.assertEqual(console_errors, [], "HR18 browser console errors: " + " | ".join(console_errors))
        self.assertEqual(static_failures, [], "HR18 HR static failures: " + " | ".join(static_failures))
