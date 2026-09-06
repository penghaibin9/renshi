"""Continue the passed empty-school lane into user-confirmed HR02 business facts.

Seed grants only permissions to the original three ordinary accounts. All
organizations, catalog and position records must be created by the browser.
"""

import argparse
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from urllib.parse import quote, urlsplit

from school_bootstrap_browser import ROOT, django_runtime, require

OUT = ROOT / "tests/artifacts/school-structure-browser"
PATH = "/hr/structure/initial-setup/"
VALUES = {"root_code": "SCHOOL-A", "department_code": "TEACHING-OFFICE",
          "department_name": "教务处", "department_type": "OFFICE", "catalog_code": "EDU-ADMIN",
          "catalog_name": "教务管理岗", "category": "MANAGEMENT", "position_code": "EDU-ADMIN-001",
          "planned_fte": "1.00", "confirmed": "on"}


def click_document(page, control, destination, *, status=200):
    """Require an actual main-frame document response, not History API noise.

    Shared shell scripts call replaceState after loading. That produces a
    same-document navigation with no response and can race expect_navigation.
    This still requires the real click, exact URL, HTTP status and loaded DOM;
    an XHR to the same URL cannot satisfy the assertion.
    """
    with page.expect_response(lambda response: (
        response.request.is_navigation_request()
        and response.frame == page.main_frame
        and response.request.method == "GET"
        and response.url == destination
    )) as received:
        control.click()
    response = received.value
    require(response.status == status,
            f"Document {destination} returned {response.status}, expected {status}")
    page.wait_for_url(destination, wait_until="domcontentloaded")
    return response


def write(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def seed():
    django_runtime()
    from django.contrib.auth.models import Permission
    from base.models import CompanyGroupAssignment
    from hr_structure.services.initialization import SETUP_PERMISSIONS
    from hr_structure.models import HrOrganization, HrPosition, HrPostCatalog

    original = ROOT / "tests/artifacts/school-bootstrap-browser"
    require(json.loads((original / "mysql-seal.json").read_text())["status"] == "PASS", "Previous bootstrap seal is required")
    data = json.loads((original / "seed.json").read_text())
    require(not any(model.objects.exists() for model in (HrOrganization, HrPostCatalog, HrPosition)),
            "Refusing to seed a non-empty structure database")
    permissions = list(Permission.objects.filter(codename__in=SETUP_PERMISSIONS))
    require({permission.codename for permission in permissions} == set(SETUP_PERMISSIONS), "Canonical permissions missing")
    for role in ("admin_a", "admin_b"):
        group = CompanyGroupAssignment.objects.get(user_id=data["roles"][role]["user_id"]).group
        group.permissions.add(*permissions)
    # The viewer also needs catalog view to read the combined receipt, never write.
    group = CompanyGroupAssignment.objects.get(user_id=data["roles"]["viewer_a"]["user_id"]).group
    group.permissions.add(Permission.objects.get(codename="hr.structure.post_catalog.view"))
    write("seed.json", data)


def browser_proof():
    from playwright.sync_api import sync_playwright

    base = os.environ.get("SCHOOL_BOOTSTRAP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    require(urlsplit(base).hostname in ("localhost", "127.0.0.1"), "Use isolated loopback runtime")
    data = json.loads((OUT / "seed.json").read_text())
    evidence = []

    def record(role, check, status):
        evidence.append({"role": role, "assertion": check, "http_status": status})
        write("evidence.json", evidence)

    def api(page, path, body=None):
        return page.evaluate("""async ({path, body}) => {
          const match = document.cookie.split(';').map(s=>s.trim()).find(s=>s.startsWith('csrftoken='));
          const options={credentials:'same-origin', headers:{'X-Requested-With':'XMLHttpRequest'}};
          if(body !== null) { options.method='POST'; options.headers['X-CSRFToken']=decodeURIComponent(match?.slice(10)||'');
            options.headers['Content-Type']='application/x-www-form-urlencoded'; options.body=new URLSearchParams(body); }
          const response=await fetch(path,options); const text=await response.text();
          let json=null; try {json=JSON.parse(text);} catch(_) {}
          return {status:response.status,json,redirected:response.redirected};
        }""", {"path": path, "body": body})

    @contextmanager
    def login(browser, role):
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(base + "/login/?next=" + quote("/settings/school-management/", safe="/"))
            page.locator("#username").fill(data["roles"][role]["username"])
            page.locator("#password").fill(os.environ["SCHOOL_BOOTSTRAP_PASSWORD"] + role)
            click_document(page, page.locator("button.yk-login-submit"), base + "/settings/school-management/")
            require(any(cookie["name"] == "sessionid" for cookie in context.cookies()), "Session not established")
            avatar = page.locator("[data-account-avatar]")
            avatar.wait_for(state="visible")
            require(avatar.inner_text().strip(), "School account avatar fallback is empty")
            require(data["roles"][role]["username"] in page.locator("[data-account-menu-toggle]").inner_text(),
                    "Shared header did not identify the signed-in school account")
            yield page
            require(not errors, f"{role}: JavaScript failures {errors}")
        except BaseException:
            page.screenshot(path=str(OUT / f"failure-{role}.png"), full_page=True)
            raise
        finally:
            context.tracing.stop(path=str(OUT / f"trace-{role}.zip"))
            context.close()

    failure = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                role = "admin_a"
                with login(browser, role) as page:
                    link = page.locator('[data-setup-step="organizations"] a')
                    click_document(page, link, base + "/hr/structure/organizations")
                    click_document(page, page.get_by_role("link", name="学校首次建立组织与岗位", exact=True), base + PATH)
                    record(role, "school-center-to-structure", 200)
                    form = page.locator("#initial-structure-form")
                    form.wait_for(state="visible")
                    proof = form.locator('[name="setup_proof"]').input_value()
                    for field, value in VALUES.items():
                        locator = form.locator(f'[name="{field}"]')
                        if field == "confirmed":
                            locator.check()
                        elif field in ("department_type", "category"):
                            locator.select_option(value)
                        else:
                            locator.fill(value)
                    with page.expect_response(lambda response: (
                        response.request.is_navigation_request()
                        and response.request.method == "POST"
                        and response.url == base + PATH
                    )) as submitted:
                        click_document(page, form.get_by_role("button", name="确认并建立组织岗位", exact=True), base + PATH)
                    require(submitted.value.status == 302, "Initial structure POST did not commit and redirect")
                    page.locator("#structure-setup-receipt").wait_for(state="visible")
                    require("教务处" in page.locator("#structure-setup-receipt").inner_text(), "Receipt did not read back the department")
                    record(role, "confirmed-real-structure-saved", 200)
                    page.reload(wait_until="domcontentloaded")
                    require("EDU-ADMIN-001" in page.locator("#structure-setup-receipt").inner_text(), "Saved position lost on refresh")
                    replay = api(page, PATH, {**VALUES, "setup_proof": proof})
                    require(replay["status"] == 200 and replay["redirected"], "Exact retry failed")
                    record(role, "same-request-retry-no-duplicate", 200)
                    conflict = api(page, PATH, {**VALUES, "setup_proof": proof, "department_name": "不得覆盖原部门"})
                    require(conflict["status"] == 409, "Conflicting replay was not rejected")
                    record(role, "changed-request-rejected", 409)
                    write("receipt.json", {"receipt_id": page.locator("#structure-setup-receipt").get_attribute("data-receipt-id")})
                    page.screenshot(path=str(OUT / "structure-receipt-desktop.png"), full_page=True)
                    click_document(page, page.get_by_role("link", name="查看正式组织树", exact=True), base + "/hr/structure/organizations")
                    page.locator("#hr-org-tree .is-root").wait_for(state="visible")
                    department_button = page.get_by_role("button").filter(has_text="教务处")
                    department_button.wait_for(state="visible")
                    root_button = page.locator("#hr-org-tree .is-root > .hr-org-node__row")
                    root_button.click()
                    require(department_button.count() == 0, "Root collapse left visible departments")
                    root_button.click()
                    department_button.wait_for(state="visible")
                    require(root_button.get_attribute("aria-expanded") == "true", "Root did not expand again")
                    record(role, "formal-root-collapse-expand", 200)
                    department_button.click()
                    page.locator("#hr-org-detail").get_by_role("heading", name="教务处", exact=True).wait_for(state="visible")
                    require("有效" in page.locator("#hr-org-detail").inner_text(), "Formal organization status was not rendered")
                    record(role, "formal-tree-and-department-read-back", 200)
                    page.goto(base + PATH)
                    click_document(page, page.get_by_role("link", name="查看岗位台账", exact=True), base + "/hr/structure/positions")
                    row = page.locator("#hr-position-table tbody tr").filter(has_text="EDU-ADMIN-001")
                    row.wait_for(state="visible")
                    require("教务处" in row.inner_text() and "空缺" in row.inner_text(), "Position not connected to formal organization/vacancy")
                    record(role, "formal-position-read-back-vacant", 200)
                    page.screenshot(path=str(OUT / "formal-position.png"), full_page=True)
                    page.goto(base + PATH)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator("#structure-setup-receipt").scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT / "structure-receipt-mobile.png"), full_page=True)

                role = "viewer_a"
                with login(browser, role) as page:
                    response = page.goto(base + PATH)
                    require(response.status == 200, "Viewer cannot read saved receipt")
                    require("EDU-ADMIN-001" in page.locator("#structure-setup-receipt").inner_text(), "Viewer cannot read saved position")
                    require(page.locator("#initial-structure-form").count() == 0, "Viewer has writable setup form")
                    denied = api(page, PATH, VALUES)
                    require(denied["status"] == 403, "Viewer write was not rejected")
                    record(role, "receipt-read-back-write-denied", 403)

                role = "admin_b"
                with login(browser, role) as page:
                    response = page.goto(base + PATH)
                    require(response.status == 200, "School B cannot read its setup state")
                    require(page.locator("#structure-setup-receipt").count() == 0, "School A receipt leaked")
                    require("EDU-ADMIN-001" not in page.locator("#hr02-initial-setup").inner_text(), "School A position leaked")
                    denied = api(page, PATH, {**VALUES, "setup_proof": proof, "tenant_id": data["school_a"]})
                    require(denied["status"] == 409, "Foreign-school proof was accepted")
                    record(role, "foreign-proof-rejected-own-school-empty", 409)
            finally:
                browser.close()
    except BaseException as exc:
        failure = exc
    write("diagnostics.json", {"failure": repr(failure) if failure else None, "completedAssertions": len(evidence)})
    if failure:
        raise failure


def seal():
    django_runtime()
    from auditlog.models import LogEntry
    from django.contrib.auth import get_user_model
    from employee.models import Employee
    from hr_staff.models import HrOutboxEvent, HrStaffMaster
    from hr_structure.models import (
        HrOrganization, HrOrganizationRelation, HrOrganizationVersion, HrPosition,
        HrPositionVersion, HrPostCatalog, HrPostCatalogVersion, HrSchoolStructureInitialization,
    )
    data = json.loads((OUT / "seed.json").read_text())
    evidence = json.loads((OUT / "evidence.json").read_text())
    expected = {("admin_a", "school-center-to-structure"): 200,
                ("admin_a", "confirmed-real-structure-saved"): 200,
                ("admin_a", "same-request-retry-no-duplicate"): 200,
                ("admin_a", "changed-request-rejected"): 409,
                ("admin_a", "formal-root-collapse-expand"): 200,
                ("admin_a", "formal-tree-and-department-read-back"): 200,
                ("admin_a", "formal-position-read-back-vacant"): 200,
                ("viewer_a", "receipt-read-back-write-denied"): 403,
                ("admin_b", "foreign-proof-rejected-own-school-empty"): 409}
    actual = {(row["role"], row["assertion"]): row["http_status"] for row in evidence}
    require(actual == expected and len(evidence) == len(expected), "Incomplete structure browser matrix")
    models = (HrOrganization, HrOrganizationVersion, HrOrganizationRelation, HrPostCatalog,
              HrPostCatalogVersion, HrPosition, HrPositionVersion, HrSchoolStructureInitialization)
    require([model.objects.filter(tenant_id=data["school_a"]).count() for model in models] == [2, 2, 1, 1, 1, 1, 1, 1],
            "Initial structure was partially created or duplicated")
    require(all(not model.objects.filter(tenant_id=data["school_b"]).exists() for model in models), "School B was changed")
    receipt = HrSchoolStructureInitialization.objects.get(tenant_id=data["school_a"])
    require(receipt.department_version.name == "教务处" and receipt.position.position_code == "EDU-ADMIN-001", "Wrong formal facts")
    require(receipt.position.organization_id_id == receipt.department_version.organization_id_id, "Position organization mismatch")
    events = HrOutboxEvent.objects.filter(tenant_id=data["school_a"], event_type__startswith="hr.structure.")
    require(events.count() == 3, "Outbox events missing or duplicated")
    audit = LogEntry.objects.get(additional_data__source="hr02_initial_structure")
    require(audit.actor_id == data["roles"]["admin_a"]["user_id"] and audit.additional_data["tenant_id"] == data["school_a"], "Wrong audit identity")
    require(not Employee.objects.exists() and not HrStaffMaster.objects.exists(), "Setup fabricated personnel")
    require(not get_user_model().objects.filter(is_superuser=True).exists(), "Browser used superuser")
    write("mysql-seal.json", {"status": "PASS", "browserAssertions": len(expected), "organizationCount": 2,
                              "positionCount": 1, "outboxEvents": 3, "auditEvents": 1, "fabricatedStaff": 0,
                              "productHead": os.environ["PRODUCT_HEAD_SHA"],
                              "testedCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("seed", "browser", "seal"))
    phase = parser.parse_args().phase
    if phase == "browser":
        # Component race cases use a fixture API and write separate evidence;
        # the real three-role/MySQL journey below remains mandatory.
        subprocess.run([sys.executable, str(ROOT / "scripts/school_structure_tree_contract.py")], check=True)
    {"seed": seed, "browser": browser_proof, "seal": seal}[phase]()
