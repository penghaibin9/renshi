"""Real Chromium/MySQL proof of first configuration without fake staff records.

Use only against the isolated Actions MySQL runtime. Seed creates school/account
identities, not personnel, organization, position, approval or result facts.
Browser saves through production pages; a separate process seals database facts.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/artifacts/school-bootstrap-browser"
PATH = "/settings/school-management/"
STATUS_PATH = PATH + "status/"
ROLE_NAMES = ("admin_a", "viewer_a", "admin_b")
NEW_NAME = "首次配置学校 A（资料已核验）"
NEW_ADDRESS = "长沙市学校首次配置验收路 1 号"


def require(value, message):
    if not value:
        raise AssertionError(message)


def write_json(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def django_runtime():
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Only the isolated Actions runtime is supported")
    require(os.environ.get("SCHOOL_BOOTSTRAP_ACCEPTANCE") == "1", "Explicit bootstrap acceptance flag required")
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")
    import django
    django.setup()
    from django.db import connection
    config = connection.settings_dict
    require(connection.vendor == "mysql", "Acceptance requires MySQL")
    require(config["NAME"] == "renshi_db", "Unexpected acceptance database")
    require(config.get("HOST") in ("127.0.0.1", "localhost"), "Acceptance database must be local")


def seed():
    django_runtime()
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission
    from base.models import Company, CompanyGroupAssignment
    from employee.models import Employee
    from hr_staff.models import HrStaffMaster
    from hr_structure.models import HrOrganization, HrPosition

    User = get_user_model()
    require(not Company.objects.exists(), "Refusing to seed an existing school database")
    require(not User.objects.exists(), "Refusing to seed an existing account database")
    schools = [Company.objects.create(company=f"首次配置学校 {label}", address="", country="CN",
                                     state="", city="", zip="") for label in ("A", "B")]
    read_codes = {"hr.structure.organization.view", "hr.structure.position.view", "hr.staff.view"}
    read_permissions = list(Permission.objects.filter(codename__in=read_codes))
    require({item.codename for item in read_permissions} == read_codes, "Canonical read permissions missing")
    roles = {}
    for name, school, can_edit in (("admin_a", schools[0], True), ("viewer_a", schools[0], False),
                                   ("admin_b", schools[1], True)):
        user = User.objects.create_user(username="bootstrap-" + name,
                                        password=os.environ["SCHOOL_BOOTSTRAP_PASSWORD"] + name)
        # Credential activation/password change is a distinct acceptance lane.
        # This fixture represents an already activated account, not an invitation.
        user.is_new_employee = False
        user.save(update_fields=["is_new_employee"])
        group = Group.objects.create(name=f"Bootstrap {name} @ {school.pk}")
        base_codes = {"view_company", "change_company"} if can_edit else {"view_company"}
        base_permissions = list(Permission.objects.filter(content_type__app_label="base", codename__in=base_codes))
        require({item.codename for item in base_permissions} == base_codes, "School profile permissions missing")
        group.permissions.set(base_permissions + read_permissions)
        CompanyGroupAssignment.objects.create(user=user, company=school, group=group)
        CompanyGroupAssignment.sync_user_group_membership(user, group)
        roles[name] = {"username": user.username, "user_id": user.pk, "school_id": school.pk}
    require(not Employee.objects.exists(), "First administrator must not create an Employee")
    require(not HrStaffMaster.objects.exists(), "First administrator must not create a staff master")
    require(not HrOrganization.objects.exists() and not HrPosition.objects.exists(), "Business facts must start empty")
    write_json("seed.json", {"roles": roles, "school_a": schools[0].pk, "school_b": schools[1].pk,
                             "school_b_name": schools[1].company})


def browser_proof():
    from playwright.sync_api import sync_playwright

    base = os.environ.get("SCHOOL_BOOTSTRAP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    require(urlsplit(base).hostname in ("127.0.0.1", "localhost"), "Browser must target isolated loopback runtime")
    data = json.loads((OUT / "seed.json").read_text(encoding="utf-8"))
    evidence = []
    failure = None

    def record(role, name, status):
        evidence.append({"role": role, "assertion": name, "http_status": status})
        write_json("evidence.json", evidence)

    def api(page, path, body=None):
        return page.evaluate("""async ({path, body}) => {
          const csrf = document.cookie.split(';').map(s => s.trim()).find(s => s.startsWith('csrftoken='));
          const headers = {'X-Requested-With':'XMLHttpRequest'};
          const options = {method: body === null ? 'GET' : 'POST', credentials:'same-origin', headers};
          if(body !== null) {
            headers['X-CSRFToken'] = csrf ? decodeURIComponent(csrf.slice(10)) : '';
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
            options.body = new URLSearchParams(body).toString();
          }
          const response = await fetch(path, options); const text = await response.text();
          let json = null; try {json = JSON.parse(text);} catch(_) {}
          return {status:response.status, json, text};
        }""", {"path": path, "body": body})

    @contextmanager
    def login(browser, role):
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            response = page.goto(base + "/login/?next=" + quote(PATH, safe="/"), wait_until="domcontentloaded")
            require(response is not None and response.status == 200, f"{role}: login page failed")
            page.locator("#username").fill(data["roles"][role]["username"])
            page.locator("#password").fill(os.environ["SCHOOL_BOOTSTRAP_PASSWORD"] + role)
            with page.expect_navigation(wait_until="domcontentloaded") as nav:
                page.locator("button.yk-login-submit").click()
            require(nav.value is not None and nav.value.status == 200, f"{role}: login destination failed")
            require(urlsplit(page.url).path == PATH, f"{role}: wrong login landing {page.url}")
            require(any(item["name"] == "sessionid" for item in context.cookies()), f"{role}: no session")
            page.locator("#school-management").wait_for(state="visible")
            require(page.locator("#school-management").get_attribute("data-school-id") == str(data["roles"][role]["school_id"]),
                    f"{role}: wrong school rendered")
            record(role, "login-without-employee", 200)
            notification_read = api(page, "/notifications/")
            require(notification_read["status"] == 200, f"{role}: account notification read failed")
            record(role, "header-notifications-readable", 200)
            yield page
            require(not errors, f"{role}: JavaScript errors {errors}")
        except BaseException:
            try:
                page.screenshot(path=str(OUT / f"failure-{role}.png"), full_page=True)
            except Exception:
                pass
            raise
        finally:
            context.tracing.stop(path=str(OUT / f"trace-{role}.zip"))
            context.close()

    def assert_summary(page, role, profile_state):
        result = api(page, STATUS_PATH)
        require(result["status"] == 200 and isinstance(result["json"], dict), f"{role}: status API failed {result}")
        summary = result["json"]
        require(summary["schoolId"] == str(data["roles"][role]["school_id"]), f"{role}: foreign summary")
        require(summary["productionReady"] is False, f"{role}: falsely production-ready")
        steps = {item["key"]: item for item in summary["steps"]}
        require(steps["profile"]["state"] == profile_state, f"{role}: profile state wrong")
        for key in ("organizations", "positions", "staff"):
            require(steps[key]["state"] == "MISSING" and steps[key]["count"] == 0, f"{role}: {key} is not empty")
        record(role, "own-school-status-" + profile_state.lower(), 200)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                role = "admin_a"
                with login(browser, role) as page:
                    assert_summary(page, role, "MISSING")
                    home = page.goto(base + "/", wait_until="domcontentloaded")
                    require(home is not None and home.status == 200 and urlsplit(page.url).path == PATH,
                            "Default home did not reach the school center")
                    record(role, "default-home-opens-school-center", 200)
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.locator('#settingsMenu:visible, a[href="/settings/"]:visible').first.click()
                    link = page.locator(f'.accordion-panel a[href="{PATH}"]')
                    require(link.count() == 1, "School-center navigation is missing or duplicated")
                    if not link.is_visible():
                        link.locator('xpath=ancestor::div[contains(@class,"accordion-panel")]').locator('xpath=preceding-sibling::button[1]').click()
                    with page.expect_response(lambda response: urlsplit(response.url).path == PATH and response.request.method == "GET") as opened:
                        link.click()
                    require(opened.value.status == 200, "School center navigation failed")
                    page.locator("#school-profile-form").wait_for(state="visible")
                    record(role, "gear-to-school-management", 200)
                    stale = page.context.new_page()
                    stale.goto(base + PATH, wait_until="domcontentloaded")
                    stale.locator("#school-profile-form").wait_for(state="visible")
                    form = page.locator("#school-profile-form")
                    for key, value in {"company": NEW_NAME, "address": NEW_ADDRESS, "country": "CN",
                                       "state": "Hunan", "city": "Changsha", "zip": "410000"}.items():
                        form.locator(f'[name="{key}"]').fill(value)
                    with page.expect_navigation(wait_until="domcontentloaded") as nav:
                        form.get_by_role("button", name="保存学校资料", exact=True).click()
                    require(nav.value is not None and nav.value.status == 200, "Profile save failed")
                    page.reload(wait_until="domcontentloaded")
                    require(page.locator('#school-profile-form [name="company"]').input_value() == NEW_NAME, "School name not persisted")
                    require(page.locator('#school-profile-form [name="address"]').input_value() == NEW_ADDRESS, "School address not persisted")
                    record(role, "profile-saved-and-reloaded", 200)
                    assert_summary(page, role, "RECORDED")
                    stale_form = stale.locator("#school-profile-form")
                    for key, value in {"company": "过期页面学校名称", "address": "过期页面不能覆盖",
                                       "country": "CN", "state": "Hunan", "city": "Changsha", "zip": "410000"}.items():
                        stale_form.locator(f'[name="{key}"]').fill(value)
                    with stale.expect_navigation(wait_until="domcontentloaded") as conflict:
                        stale.get_by_role("button", name="保存学校资料", exact=True).click()
                    require(conflict.value is not None and conflict.value.status == 409, "Stale tab overwrite was not rejected")
                    record(role, "stale-edit-denied", 409)
                    stale.close()
                    page.screenshot(path=str(OUT / "school-a-configured.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator("#school-profile-form").scroll_into_view_if_needed()
                    with page.expect_navigation(wait_until="domcontentloaded") as mobile_save:
                        page.get_by_role("button", name="保存学校资料", exact=True).click()
                    require(mobile_save.value is not None and mobile_save.value.status == 200, "Mobile profile save failed")
                    record(role, "mobile-save-from-ui", 200)
                    page.screenshot(path=str(OUT / "school-a-mobile.png"), full_page=True)

                role = "viewer_a"
                with login(browser, role) as page:
                    require(page.locator('#school-profile-form [name="company"]').input_value() == NEW_NAME,
                            "Read-only role did not read back the saved school name")
                    require(page.locator('#school-profile-form [name="address"]').input_value() == NEW_ADDRESS,
                            "Read-only role did not read back the saved school address")
                    record(role, "saved-profile-read-back-by-viewer", 200)
                    require(page.get_by_role("button", name="保存学校资料", exact=True).count() == 0, "Read-only save control rendered")
                    token = page.locator('[name="profile_token"]').input_value()
                    denied = api(page, PATH, {"profile_token": token, "company": "不能更改", "address": "不能更改"})
                    require(denied["status"] == 403, f"Read-only write was not denied: {denied}")
                    record(role, "profile-write-denied", 403)

                role = "admin_b"
                with login(browser, role) as page:
                    require(NEW_NAME not in page.locator("#school-management").inner_text(), "School A data leaked")
                    assert_summary(page, role, "MISSING")
                    for prefix in ("/settings/company-update/", "/company-update-form/"):
                        target = prefix + str(data["school_a"]) + "/"
                        result = api(page, target, {"company": "跨校不能改", "address": "跨校不能改"})
                        require(result["status"] == 404, f"Cross-school mutation not concealed: {result}")
                    record(role, "foreign-school-writes-concealed", 404)
                    result = api(page, "/company-create-form/", {"company": "不能替平台开户"})
                    require(result["status"] == 403, "School administrator was allowed to create tenants")
                    record(role, "platform-create-denied", 403)
                    page.screenshot(path=str(OUT / "school-b-still-empty.png"), full_page=True)
            finally:
                browser.close()
    except BaseException as exc:
        failure = exc
    write_json("diagnostics.json", {"failure": repr(failure) if failure else None, "completedAssertions": len(evidence)})
    if failure:
        raise failure


def seal():
    django_runtime()
    from auditlog.models import LogEntry
    from django.contrib.auth import get_user_model
    from base.models import Company
    from employee.models import Employee
    from hr_staff.models import HrStaffMaster
    from hr_structure.models import HrOrganization, HrPosition
    data = json.loads((OUT / "seed.json").read_text(encoding="utf-8"))
    evidence = json.loads((OUT / "evidence.json").read_text(encoding="utf-8"))
    expected = {
        ("admin_a", "login-without-employee"): 200,
        ("admin_a", "header-notifications-readable"): 200,
        ("admin_a", "own-school-status-missing"): 200,
        ("admin_a", "gear-to-school-management"): 200,
        ("admin_a", "default-home-opens-school-center"): 200,
        ("admin_a", "profile-saved-and-reloaded"): 200,
        ("admin_a", "own-school-status-recorded"): 200,
        ("admin_a", "stale-edit-denied"): 409,
        ("admin_a", "mobile-save-from-ui"): 200,
        ("viewer_a", "login-without-employee"): 200,
        ("viewer_a", "header-notifications-readable"): 200,
        ("viewer_a", "profile-write-denied"): 403,
        ("viewer_a", "saved-profile-read-back-by-viewer"): 200,
        ("admin_b", "login-without-employee"): 200,
        ("admin_b", "header-notifications-readable"): 200,
        ("admin_b", "own-school-status-missing"): 200,
        ("admin_b", "foreign-school-writes-concealed"): 404,
        ("admin_b", "platform-create-denied"): 403,
    }
    actual = {(row["role"], row["assertion"]): row["http_status"] for row in evidence}
    require(actual == expected and len(evidence) == len(expected), "Incomplete or duplicate browser role matrix")
    school_a = Company.objects.get(pk=data["school_a"])
    school_b = Company.objects.get(pk=data["school_b"])
    require(school_a.company == NEW_NAME and school_a.address == NEW_ADDRESS, "School A mutation mismatch")
    require(school_b.company == data["school_b_name"] and school_b.address == "", "School B was mutated")
    require(Company.objects.count() == 2, "Unexpected extra school")
    require(not get_user_model().objects.filter(is_superuser=True).exists(), "Acceptance used a superuser")
    require(not Employee.objects.exists() and not HrStaffMaster.objects.exists(), "Fake personnel facts created")
    require(not HrOrganization.objects.exists() and not HrPosition.objects.exists(), "Fake structure facts created")
    events = LogEntry.objects.filter(object_pk=str(school_a.pk), additional_data__source="school_management")
    require(events.count() == 1, f"Unexpected profile audit count: {events.count()}")
    event = events.get()
    require(event.actor_id == data["roles"]["admin_a"]["user_id"], "Wrong audit actor")
    require(event.additional_data["tenant_id"] == school_a.pk, "Wrong audit tenant")
    require(not LogEntry.objects.filter(object_pk=str(school_b.pk), additional_data__source="school_management").exists(),
            "School B has unexpected mutation audit")
    write_json("mysql-seal.json", {"status": "PASS", "schoolCount": 2, "fakeStaffCount": 0,
                                   "profileAuditCount": 1, "browserAssertions": len(evidence),
                                   "productHead": os.environ.get("PRODUCT_HEAD_SHA"),
                                   "testedCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()})
    print("School bootstrap MySQL and Chromium seal PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("seed", "browser", "seal"))
    phase = parser.parse_args().phase
    {"seed": seed, "browser": browser_proof, "seal": seal}[phase]()
