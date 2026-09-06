"""Real first-password UI before the existing empty-school acceptance journey.

No tracing of credential request bodies. Only bounded status metadata and
screenshots with empty/password-masked inputs are retained. This is not an
invitation delivery or account creation test: the parent lane owns the seed.
"""
import json
import os
from urllib.parse import urlsplit


def verify_first_password(browser, *, base, data, record, out, require):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    native_posts = []
    origin = urlsplit(base)
    expected_origin = f"{origin.scheme}://{origin.netloc}"
    page.on("pageerror", lambda error: errors.append(str(error)))
    role = "admin_a"
    current = os.environ["SCHOOL_BOOTSTRAP_PASSWORD"] + role + "-initial"
    desired = os.environ["SCHOOL_BOOTSTRAP_PASSWORD"] + role
    try:
        page.goto(base + "/login/?next=/settings/school-management/", wait_until="domcontentloaded")
        page.locator("#username").fill(data["roles"][role]["username"])
        page.locator("#password").fill(current)
        with page.expect_navigation(wait_until="domcontentloaded") as navigation:
            page.locator("button.yk-login-submit").click()
        require(navigation.value is not None and navigation.value.status == 200, "First-password landing failed")
        require(urlsplit(page.url).path == "/change-password/", "Required password change was bypassed")
        page.locator("#account-password-form").wait_for(state="visible")
        page.screenshot(path=str(out / "first-password-desktop.png"), full_page=True)
        record(role, "first-password-required-before-school-access", 200)
        denied = context.request.get(base + "/settings/school-management/status/", headers={
            "HX-Request": "true", "HX-Current-URL": base + "/change-password/",
        }, max_redirects=0)
        require(denied.status == 204 and denied.headers.get("hx-redirect") == "/change-password/",
                "Client current-page header admitted protected school access")
        record(role, "first-password-spoofed-page-header-denied", 204)

        def submit(case, old, new, confirm, expected_post_status):
            page.locator("#id_old_password").fill(old)
            page.locator("#id_new_password").fill(new)
            page.locator("#id_confirm_password").fill(confirm)
            # Observe browser-generated headers. Never inject Origin/Referer
            # or emulate this native form with context.request/fetch.
            with page.expect_navigation(wait_until="domcontentloaded") as response:
                with page.expect_response(lambda item: item.url == base + "/change-password/"
                                          and item.request.method == "POST") as submitted:
                    page.locator('#account-password-form button[type="submit"]').click()
            native = submitted.value
            actual_origin = native.request.header_value("origin")
            native_posts.append({"case": case, "method": native.request.method,
                                 "origin": actual_origin, "httpStatus": native.status,
                                 "finalStatus": response.value.status if response.value else None,
                                 "finalPath": urlsplit(page.url).path})
            require(actual_origin == expected_origin,
                    f"Native password form did not send its own origin ({case})")
            require(native.status == expected_post_status,
                    f"Password form {case}: expected HTTP {expected_post_status}, got {native.status}")
            return response.value

        invalid = submit("invalid-old", "incorrect-initial-password", desired, desired, 400)
        require(invalid is not None and invalid.status == 400, "Incorrect-password validation response missing")
        require(page.locator("#old-password-errors .errorlist").count() == 1, "Current-password error missing")
        record(role, "first-password-invalid-old-denied", 400)
        weak = submit("weak-new", current, "123", "123", 400)
        require(weak is not None and weak.status == 400, "Configured password validators were bypassed")
        require(page.locator("#new-password-errors .errorlist").count() == 1, "Password guidance missing")
        record(role, "first-password-weak-password-denied", 400)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(out / "first-password-mobile.png"), full_page=True)
        success = submit("save", current, desired, desired, 302)
        require(success is not None and success.status == 200, "First password was not saved")
        require(urlsplit(page.url).path == "/settings/school-management/", "New school account did not reach its center")
        page.locator("#school-management").wait_for(state="visible")
        require(page.locator("#school-management").get_attribute("data-school-id") == str(data["school_a"]),
                "Password setup changed the user's school")
        page.reload(wait_until="domcontentloaded")
        page.locator("#school-management").wait_for(state="visible")
        record(role, "first-password-saved-and-school-center-reloaded", 200)
        require(not errors, "First-password page JavaScript error")
    except BaseException:
        page.screenshot(path=str(out / "first-password-failure.png"), full_page=True)
        raise
    finally:
        # No bodies, password values, tokens or cookies enter this artifact.
        (out / "first-password-transport.json").write_text(json.dumps({
            "productHead": os.environ.get("PRODUCT_HEAD_SHA"),
            "kind": "real-browser-native-form-header-and-status-metadata",
            "expectedOrigin": expected_origin, "requests": native_posts,
        }, indent=2), encoding="utf-8")
        context.close()
