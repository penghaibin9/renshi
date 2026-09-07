"""HR01 workforce read-only acceptance through real login, Django and MySQL.

Synthetic school/accounts are authentication prerequisites, not completed HR
business facts. Responses are neither replaced nor seeded in the browser.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from unittest import skipUnless
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

API = "/api/v1/hr/home/workforce/"
DIMENSIONS = ("personnel_category", "department", "job_position", "gender", "age_group")


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "explicit real browser audit")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="hr01-workforce-audit-"))
class HrWorkforceVisualAuditTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation

        self.company = Company.objects.create(
            company="跃科队伍结构验收学校（合成）", hq=True, address="隔离验收环境",
            country="CN", state="Hunan", city="Changsha", zip="410000",
            icon=SimpleUploadedFile("workforce.png", base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            ), content_type="image/png"),
        )
        self.secret = "Isolated-Workforce-Only-8431"
        self.admin = get_user_model().objects.create_superuser(
            username="workforce-admin", email="workforce-admin@example.invalid", password=self.secret,
        )
        self.denied = get_user_model().objects.create_user(
            username="workforce-no-access", email="workforce-denied@example.invalid", password=self.secret,
        )
        for index, user in enumerate((self.admin, self.denied)):
            user.is_new_employee = False
            user.save(update_fields=["is_new_employee"])
            employee = Employee.objects.create(
                employee_user_id=user, employee_first_name="合成队伍验收", employee_last_name=str(index),
                email=f"workforce-employee-{index}@example.invalid", phone=f"1380000843{index}", is_active=True,
            )
            work, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=employee)
            work.company_id = self.company
            work.save(update_fields=["company_id"])
        self.out = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "HR01-WORKFORCE"
        self.out.mkdir(parents=True, exist_ok=True)

    def login(self, page, user):
        response = page.goto(self.live_server_url + "/login/?next=/hr/workforce", wait_until="networkidle")
        self.assertEqual(response.status, 200)
        page.locator("#username").fill(user.username)
        page.locator("#password").fill(self.secret)
        with page.expect_response(lambda r: r.request.is_navigation_request() and r.request.method == "GET" and urlsplit(r.url).path == "/hr/workforce") as signed_in:
            page.locator("button.yk-login-submit").click()
        return signed_in.value

    def check_distribution(self, page, payload):
        from playwright.sync_api import expect

        region = page.locator("#hr-workforce-dist")
        expect(region).to_have_attribute("aria-busy", "false", timeout=18000)
        expect(region.locator(".hr-skeleton")).to_have_count(0)
        self.assertIn(payload["status"], {"OK", "PARTIAL", "STALE", "UNAVAILABLE"})
        if payload["status"] == "UNAVAILABLE":
            expect(region).to_have_attribute("data-state", "unavailable")
            expect(region.locator(".wf-table")).to_have_count(0)
        else:
            buckets = payload["data"]["buckets"]
            if not buckets:
                expect(region).to_have_attribute("data-state", "empty" if payload["status"] == "OK" else "unavailable")
            else:
                expect(region.locator("tbody th")).to_have_text([str(item["label"]) for item in buckets])
                expect(region.locator(".wf-count")).to_have_text([str(item["count"]) for item in buckets])
                expect(region.locator('[data-count-kind="masked"] .wf-bar')).to_have_count(0)

    def test_real_login_all_dimensions_refresh_and_mobile(self):
        from playwright.sync_api import expect, sync_playwright
        from employee.models import Employee

        before_count = Employee._base_manager.count()
        records, errors, failures = [], [], []
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda r: failures.append(f"{r.status} {urlsplit(r.url).path}") if (API in r.url or "/static/hr/" in r.url) and r.status >= 400 else None)
                self.assertEqual(self.login(page, self.admin).status, 200)
                for mode, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
                    page.set_viewport_size(viewport)
                    with page.expect_response(lambda r: urlsplit(r.url).path == API + "summary") as summarized:
                        response = page.goto(self.live_server_url + "/hr/workforce", wait_until="networkidle")
                    self.assertEqual(response.status, 200)
                    self.assertEqual(summarized.value.status, 200)
                    payload = summarized.value.json()
                    expect(page.locator("#hr-workforce-summary")).to_have_attribute("aria-busy", "false", timeout=18000)
                    expect(page.locator(".wf-kpi")).to_have_count(3)
                    for index, key in enumerate(("headcount", "fullTimeTeacher", "doubleTeacher")):
                        item = next(row for row in payload["data"]["conclusions"] if row["key"] == key)
                        readable = item["status"] in {"OK", "PARTIAL", "STALE"}
                        expected = str(item["value"]) if readable and item.get("value") is not None else "—"
                        expect(page.locator(".wf-kpi strong").nth(index)).to_have_text(expected)
                    for dimension in DIMENSIONS:
                        button = page.locator(f'[data-dim="{dimension}"]')
                        with page.expect_response(lambda r: urlsplit(r.url).path == API + "distribution" and parse_qs(urlsplit(r.url).query).get("dimension") == [dimension]) as distributed:
                            button.click()
                        self.assertEqual(distributed.value.status, 200)
                        actual = distributed.value.json()
                        self.check_distribution(page, actual)
                        expect(button).to_have_attribute("aria-pressed", "true")
                        expect(page.locator('[data-dim][aria-pressed="true"]')).to_have_count(1)
                        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth-innerWidth"), 1)
                        self.assertLessEqual(page.locator(".hr-workforce").evaluate("n=>n.scrollWidth-n.clientWidth"), 1)
                        if mode == "mobile":
                            self.assertGreaterEqual(button.bounding_box()["height"], 44)
                        page.screenshot(path=str(self.out / f"{mode}-{dimension}.png"), full_page=True)
                        records.append({"mode": mode, "dimension": dimension, "httpStatus": distributed.value.status,
                                        "status": actual["status"], "requestId": actual.get("requestId"), "dataBasis": actual.get("dataBasis")})
                    with page.expect_response(lambda r: urlsplit(r.url).path == API + "distribution") as refreshed:
                        page.locator("[data-workforce-refresh]").click()
                    self.assertEqual(refreshed.value.status, 200)
                    self.check_distribution(page, refreshed.value.json())
                    expect(page.locator("[data-workforce-refresh]")).to_be_enabled(timeout=18000)
                    page.locator(".wf-sources summary").click()
                    page.locator(".wf-sources").scroll_into_view_if_needed()
                    page.screenshot(path=str(self.out / f"{mode}-source-details.png"), full_page=True)
                context.close()
            finally:
                browser.close()
                (self.out / "read-seal.json").write_text(json.dumps({
                    "scope": "real login/read-only workforce; synthetic identities; no mocked API",
                    "productSha": os.getenv("HR_PRODUCT_SHA", "UNSPECIFIED"), "checkoutSha": os.getenv("GITHUB_SHA", "LOCAL"),
                    "records": records, "pageErrors": errors, "httpFailures": failures,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assertEqual(errors, [])
        self.assertEqual(failures, [])
        self.assertEqual(len(records), 10)
        self.assertEqual(Employee._base_manager.count(), before_count)

    def test_unprivileged_real_login_cannot_read_workforce_page_or_apis(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                self.assertEqual(self.login(page, self.denied).status, 403)
                self.assertEqual(page.locator("#hr-workforce-summary").count(), 0)
                for suffix in ("summary", "distribution?dimension=gender"):
                    response = context.request.get(self.live_server_url + API + suffix)
                    self.assertEqual(response.status, 403)
                    self.assertEqual(response.json()["error"]["code"], "PERMISSION_DENIED")
                page.screenshot(path=str(self.out / "permission-denied.png"), full_page=True)
                context.close()
            finally:
                browser.close()
