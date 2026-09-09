"""Read-only real Django/MySQL/Chromium page census, not business-chain sign-off.

Enumerate the registered HR page modules (including aliases and detail patterns).
Authenticate through the production login form. Synthetic identity prerequisites
are labelled; no business action is submitted to fill empty workspaces. Missing
business objects remain NOT_RUN in the denominator instead of invented IDs.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import json
import os
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import URLPattern

PAGE_MODULES = [
    ("HR01", "hr_control_center.urls", "hr/"),
    ("HR02", "hr_structure.urls", "hr/structure/"),
    ("HR03", "hr_staff.urls", "hr/staff/"),
    ("HR04", "hr_recruitment.urls", "hr/recruitment/"),
    ("HR05", "hr_onboarding.urls", "hr/onboarding/"),
    ("HR06", "hr_changes.urls", "hr/changes/"),
    ("HR07", "hr_contracts.urls", "hr/contracts/"),
    ("HR08", "hr_external.urls", "hr/external-teachers/"),
    ("HR09", "hr_qualification.urls", "hr/qualifications/"),
    ("HR09", "hr_qualification.urls_double_teacher", "hr/double-teacher/"),
    ("HR10", "hr10_development.urls", ""),
    ("HR11", "hr_time.urls", "hr/time/"),
    ("HR12", "hr_assessment.urls", "hr/assessments/"),
    ("HR13", "hr_title.urls", "hr/titles/"),
    ("HR14", "hr_appointment.urls", "hr/appointments/"),
    ("HR15", "hr_payroll.urls", "hr/payroll/"),
    ("HR16", "hr_exit.urls", "hr/exit/"),
    ("HR17", "hr_self.urls", "hr/self/"),
    ("HR18", "hr_data.urls", "hr/data/"),
]

# Read-only DOM measurements; scroll offsets may change for capture, never CSS/data.
MEASURE = r"""() => {
 const visible = n => {const r=n.getBoundingClientRect();const s=getComputedStyle(n);
   return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';};
 const root=document.querySelector('.hr-v2-page')||document.querySelector('main[data-module],main')||document.body;
 const controls=[...root.querySelectorAll('button,input:not([type=hidden]),select,textarea,a[href]')].filter(visible);
 const scrollers=[...document.querySelectorAll('*')].filter(n=>{
   const s=getComputedStyle(n);return visible(n)&&n.clientHeight>100&&n.scrollHeight>n.clientHeight+20&&/(auto|scroll)/.test(s.overflowY);
 }).map(n=>({selector:n.id?'#'+CSS.escape(n.id):null,tag:n.tagName,classes:n.className,
   height:n.clientHeight,total:n.scrollHeight,top:n.scrollTop,width:n.clientWidth}));
 return {title:document.title,h1:[...root.querySelectorAll('h1')].map(n=>({text:n.textContent.trim(),size:getComputedStyle(n).fontSize,weight:getComputedStyle(n).fontWeight})),
   module:root.dataset.module||'',heading:root.querySelector('h1,h2')?.textContent.trim()||'',
   documentOverflow:document.documentElement.scrollWidth-innerWidth,
   rootWidth:root.getBoundingClientRect().width,viewport:innerWidth,
   visibleSkeletons:[...root.querySelectorAll('.hr-skeleton,[aria-busy=true]')].filter(visible).length,
   smallControls:controls.filter(n=>{let r=n.getBoundingClientRect();return r.height<32&&r.width>12}).slice(0,30).map(n=>({tag:n.tagName,text:n.textContent.trim().slice(0,50),height:n.getBoundingClientRect().height})),
   unlabeledInputs:controls.filter(n=>n.matches('input,textarea,select')&&!n.labels?.length&&!n.getAttribute('aria-label')&&!n.getAttribute('aria-labelledby')).map(n=>n.name||n.id||n.tagName),
   scrollers};
}"""


@skipUnless(os.getenv("HR_VISUAL_AUDIT") == "1", "explicit CI page census")
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="renshi-page-inventory-"))
class HrPageInventoryTests(StaticLiveServerTestCase):
    reset_sequences = True

    def setUp(self):
        from base.models import Company
        from employee.models import Employee, EmployeeWorkInformation
        from hr_staff.models import HrPerson, HrStaffMaster

        self.school = Company.objects.create(
            company="跃科逐页巡检学校（合成测试）", hq=True, address="测试环境",
            country="CN", state="Hunan", city="Changsha", zip="410000",
            icon=SimpleUploadedFile("inventory.png", base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="), content_type="image/png"),
        )
        self.password = "Inventory-Only-Test-8137"
        self.user = get_user_model().objects.create_superuser(
            username="hr-page-inventory", email="page-inventory@example.invalid", password=self.password,
        )
        self.user.is_new_employee = False
        self.user.save(update_fields=["is_new_employee"])
        self.employee = Employee.objects.create(
            employee_user_id=self.user, employee_first_name="合成", employee_last_name="巡检员",
            email="inventory-employee@example.invalid", phone="13800008137", is_active=True,
        )
        work, _ = EmployeeWorkInformation._base_manager.get_or_create(employee_id=self.employee)
        work.company_id = self.school
        work.save(update_fields=["company_id"])
        person = HrPerson.objects.create(tenant_id=self.school.pk, legal_name="合成巡检人员")
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.school.pk, person_id=person, staff_no="INVENTORY-ONLY-001",
            legacy_employee_id=self.employee.pk,
        )
        self.out = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "PAGE-INVENTORY"
        self.out.mkdir(parents=True, exist_ok=True)
        self.rows = []

    def routes(self):
        for module, dotted, prefix in PAGE_MODULES:
            for pattern in importlib.import_module(dotted).urlpatterns:
                if not isinstance(pattern, URLPattern):
                    raise AssertionError(f"Unenumerated nested page resolver: {dotted}")
                route = "/" + prefix + str(pattern.pattern)
                if not route.startswith("/hr/"):
                    raise AssertionError(f"Unexpected non-HR route: {route}")
                original = route
                bound = False
                if module == "HR03" and "<uuid:staff_id>" in route:
                    route = route.replace("<uuid:staff_id>", str(self.staff.pk)); bound = True
                if module == "HR10" and "<int:staff_id>" in route:
                    route = route.replace("<int:staff_id>", str(self.employee.pk)); bound = True
                yield {"module": module, "pattern": original, "route": route,
                       "name": pattern.name or "(redirect)", "source": dotted,
                       "identityDetail": bound, "parameterized": "<" in original}

    def save(self):
        report = {"productSha": os.getenv("HR_PRODUCT_SHA", "UNSPECIFIED"),
                  "checkoutSha": os.getenv("GITHUB_SHA", "LOCAL"),
                  "runId": os.getenv("GITHUB_RUN_ID", "LOCAL"),
                  "environment": "real isolated Django/MySQL server and Chromium; synthetic technical administrator",
                  "scope": "read-only registered HR pages plus production login; not multi-role business acceptance",
                  "rows": self.rows}
        (self.out / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        columns = ["module", "pattern", "route", "mode", "status", "httpStatus", "finalPath", "reason", "screenshot"]
        with (self.out / "inventory.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader(); writer.writerows(self.rows)

    def capture(self, page, stem):
        shots = []
        # First paint captures the actual viewport. Then scroll the principal
        # content panel so full_page=True cannot silently omit its lower content.
        top = self.out / f"{stem}-top.png"
        page.screenshot(path=str(top), full_page=True)
        shots.append({"file": top.name, "sha256": hashlib.sha256(top.read_bytes()).hexdigest()})
        panel = page.evaluate_handle("""() => [...document.querySelectorAll('*')].filter(n=>{
          const r=n.getBoundingClientRect(),s=getComputedStyle(n);
          return r.width>200&&r.height>200&&n.scrollHeight>n.clientHeight+30&&/(auto|scroll)/.test(s.overflowY);
        }).sort((a,b)=>b.clientWidth-a.clientWidth)[0] || document.scrollingElement""")
        geometry = panel.evaluate("n=>({height:n.clientHeight,total:n.scrollHeight})")
        height = max(1, geometry["height"])
        max_top = max(0, geometry["total"] - height)
        positions = list(range(height, max_top, height)) + ([max_top] if max_top else [])
        clipped = len(positions) > 5
        if clipped:
            positions = positions[:4] + [max_top]
        for i, pos in enumerate(positions, 1):
            panel.evaluate("(n,y)=>{n.scrollTop=y}", pos)
            page.wait_for_timeout(80)
            path = self.out / f"{stem}-scroll-{i}.png"
            page.screenshot(path=str(path), full_page=True)
            shots.append({"file": path.name, "scrollTop": pos, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        panel.dispose()
        return shots, clipped

    def test_registered_pages_real_login_desktop_and_mobile(self):
        from playwright.sync_api import sync_playwright

        routes = list(self.routes())
        failures = []
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                response = page.goto(self.live_server_url + "/login/?next=/hr/overview", wait_until="domcontentloaded")
                self.assertEqual(response.status, 200)
                page.screenshot(path=str(self.out / "login-before.png"), full_page=True)
                page.locator("#username").fill(self.user.username)
                page.locator("#password").fill(self.password)
                with page.expect_response(lambda r: r.request.is_navigation_request() and r.request.method == "GET" and "/hr/overview" in r.url) as signed_in:
                    page.locator("button.yk-login-submit").click()
                self.assertEqual(signed_in.value.status, 200)
                self.assertIn("/hr/overview", page.url)
                errors, api_errors = [], []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.on("response", lambda r: api_errors.append(f"{r.status} {r.url.replace(self.live_server_url, '')}") if "/api/v1/hr/" in r.url and r.status >= 400 else None)
                for mode, viewport in (("desktop", {"width":1440,"height":1000}), ("mobile", {"width":390,"height":844})):
                    page.set_viewport_size(viewport)
                    for index, entry in enumerate(routes, 1):
                        row = {**entry, "mode": mode, "status": "NOT_RUN"}
                        if "<" in entry["route"]:
                            row["reason"] = "缺少按正式业务路径建立的案件/聘用对象；不伪造 UUID 或已办结事实"
                            self.rows.append(row); self.save(); continue
                        errors.clear(); api_errors.clear()
                        stem = f"{index:03d}-{entry['module']}-{mode}"
                        try:
                            response = page.goto(self.live_server_url + entry["route"], wait_until="networkidle", timeout=25000)
                            row["httpStatus"] = response.status if response else None
                            row["finalPath"] = page.url.replace(self.live_server_url, "")
                            if "/login" in page.url or "/change-password" in page.url:
                                raise AssertionError("页面退回认证入口，不能记为业务页通过")
                            # Let bounded production API timeouts settle; record,
                            # rather than conceal, a still-loading surface.
                            try:
                                page.wait_for_function("""() => ![...document.querySelectorAll('.hr-skeleton')].some(n=>n.getBoundingClientRect().height>0)""", timeout=18000)
                            except Exception:
                                row["loadingUnsettled"] = True
                            row["geometry"] = page.evaluate(MEASURE)
                            shots, clipped = self.capture(page, stem)
                            row["screenshots"] = shots
                            row["screenshot"] = shots[0]["file"]
                            row["scrollCoverageIncomplete"] = clipped
                            row["pageErrors"] = list(errors)
                            row["apiErrors"] = list(api_errors)
                            unexpected = row["httpStatus"] != 200 or bool(errors) or any(x.startswith("5") for x in api_errors)
                            row["status"] = "FAIL" if unexpected else "CAPTURED"
                            row["reason"] = "只证明实际页面读取和截图；交互/角色/业务链须独立验收"
                            if unexpected:
                                failures.append(f"{mode} {entry['route']}: HTTP {row['httpStatus']} {errors} {api_errors}")
                        except Exception as exc:
                            row["status"] = "FAIL"; row["reason"] = str(exc)[:1200]
                            failures.append(f"{mode} {entry['route']}: {row['reason']}")
                            try:
                                path = self.out / f"{stem}-blocked.png"
                                page.screenshot(path=str(path), full_page=True)
                                row["screenshot"] = path.name
                            except Exception:
                                pass
                        self.rows.append(row); self.save()
                context.close()
            finally:
                browser.close(); self.save()
        print(f"HR page patterns: {len(routes)}; captures/records: {len(self.rows)}; unexpected failures: {len(failures)}")
        self.assertEqual(failures, [], "\n".join(failures))
