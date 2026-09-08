"""Production DOM/JS with isolated location/HTTP; not navigation or MySQL proof."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://activation.invalid"
PATH = "/activate-account/00000000-0000-4000-8000-000000000001/"
TOKEN = "synthetic-ui-only-invitation-" + "x" * 40


class AccountActivationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = sync_playwright().start()
        cls.addClassCleanup(cls.runtime.stop)
        options = {"headless": True}
        if path := os.getenv("HR_UI_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = path
        cls.browser = cls.runtime.chromium.launch(**options)
        cls.addClassCleanup(cls.browser.close)

    def mount(self, *, token=TOKEN, width=1440):
        context = self.browser.new_context(viewport={"width": width, "height": 844 if width <= 760 else 1000})
        self.addCleanup(context.close)
        page = context.new_page()
        source = (ROOT / "backend/base/templates/base/account/invitation_activate.html").read_text()
        source = re.sub(r"{%\s*if not [^%]+%}hidden{%\s*endif\s*%}", "hidden", source)
        source = source.replace("{% load static %}", "")
        source = source.replace("{% static 'base/js/account_invitation.js' %}", "/static/base/js/account_invitation.js")
        source = source.replace("{% csrf_token %}", '<input name="csrfmiddlewaretoken" type="hidden" value="isolated-csrf">')
        source = re.sub(r"{{[^}]+}}", "", source)
        self.assertNotIn("{%", source)
        # Deliberately isolate URL/history/HTTP APIs: no host navigation or
        # security-policy modification is needed for this DOM unit suite.
        source = re.sub(r"<script[^>]+></script>", "", source)
        page.set_content(source)
        page.evaluate("""config => {
          window.testPosts=[];window.testMode='field';window.testField='password';
          window.testMessage='密码不符合安全策略';window.testPending=null;
          window.testLocation={hash:config.token?'#'+config.token:'',pathname:config.path,search:'',assigned:null,
            assign(value){this.assigned=value}};
          window.testWindow={location:window.testLocation,document,
            history:{replaceState(state,title,path){window.testLocation.hash='';window.testHistory={state,path}}},
            setTimeout:window.setTimeout.bind(window),clearTimeout:window.clearTimeout.bind(window),
            addEventListener:window.addEventListener.bind(window)};
          window.testRespond=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
          window.testFetch=(url,options)=>{
            window.testPosts.push({url,entries:Object.fromEntries(options.body.entries()),headers:options.headers,
              method:options.method,credentials:options.credentials,mode:options.mode,redirect:options.redirect});
            if(window.testMode==='hold')return new Promise(resolve=>{window.testPending=resolve});
            if(window.testMode==='network')return Promise.reject(new Error('isolated offline'));
            if(window.testMode==='malformed')return Promise.resolve(new Response('not-json'));
            if(window.testMode==='denied')return Promise.resolve(new Response('denied',{status:403}));
            if(window.testMode==='success')return Promise.resolve(testRespond({ok:true,next:'/account-activation-complete/'}));
            return Promise.resolve(testRespond({ok:false,errors:{[window.testField]:window.testMessage}},400));
          };
        }""", {"token": token, "path": PATH})
        script = (ROOT / "backend/base/static/base/js/account_invitation.js").read_text()
        page.evaluate("script=>Function('window','fetch',script)(window.testWindow,window.testFetch)", script)
        page.locator("#id_username").fill("synthetic-teacher")
        page.locator("#id_password").fill("Only-Synthetic-Password-7482")
        page.locator("#id_confirm_password").fill("Only-Synthetic-Password-7482")
        return page

    def test_recoverable_error_keeps_secret_only_in_memory_and_retries(self):
        page = self.mount()
        page.locator("#account-invitation-submit").click()
        expect(page.locator("#error-password")).to_have_text(page.evaluate("testMessage"))
        expect(page.locator("#id_password")).to_be_focused()
        expect(page.locator("#account-invitation-submit")).to_be_enabled()
        self.assertEqual(page.evaluate("testLocation.hash"), "")
        self.assertEqual(page.evaluate("testHistory"), {"state": None, "path": PATH})
        self.assertEqual(page.locator("#id_activation_token").input_value(), "")
        self.assertNotIn(TOKEN, page.content())
        self.assertNotIn(TOKEN, str(page.evaluate("testHistory")))
        page.evaluate("testMode='success'")
        page.locator("#account-invitation-submit").click()
        page.wait_for_function("testLocation.assigned==='/account-activation-complete/'")
        self.assertEqual(page.evaluate("testPosts.length"), 2)
        self.assertTrue(page.evaluate("token=>testPosts.every(r=>r.entries.activation_token===token)", TOKEN))
        self.assertTrue(page.evaluate("token=>testPosts.every(r=>!r.url.includes(token))", TOKEN))

    def test_mismatched_passwords_do_not_send_a_request(self):
        page = self.mount()
        page.locator("#id_confirm_password").fill("different")
        page.locator("#account-invitation-submit").click()
        expect(page.locator("#id_confirm_password")).to_be_focused()
        expect(page.locator("#error-confirm_password")).to_contain_text("不一致")
        self.assertEqual(page.evaluate("testPosts"), [])

    def test_pending_submission_cannot_duplicate(self):
        page = self.mount()
        page.evaluate("testMode='hold'")
        page.locator("#account-invitation-submit").click()
        expect(page.locator("form")).to_have_attribute("aria-busy", "true")
        expect(page.locator("#account-invitation-submit")).to_be_disabled()
        page.locator("#id_username").press("Enter")
        self.assertEqual(page.evaluate("testPosts.length"), 1)
        page.evaluate("testPending(testRespond({ok:false,errors:{username:'账号已使用'}},400))")
        expect(page.locator("#id_username")).to_be_focused()
        expect(page.locator("#account-invitation-submit")).to_be_enabled()

    def test_terminal_error_clears_secrets_and_stops(self):
        page = self.mount()
        page.evaluate("testField='__all__';testMessage='邀请链接已失效'")
        page.locator("#account-invitation-submit").click()
        expect(page.locator("#activation-errors")).to_have_text("邀请链接已失效")
        expect(page.locator("#account-invitation-submit")).to_be_disabled()
        self.assertEqual(page.locator("#id_password").input_value(), "")
        self.assertEqual(page.evaluate("testPosts.length"), 1)

    def test_unknown_responses_never_auto_retry_or_claim_rollback(self):
        for mode in ("network", "malformed"):
            with self.subTest(mode=mode):
                page = self.mount()
                page.evaluate("mode=>testMode=mode", mode)
                page.locator("#account-invitation-submit").click()
                expect(page.locator("#activation-errors")).to_contain_text("结果尚未确认")
                expect(page.locator("#account-invitation-submit")).to_be_disabled()
                self.assertEqual(page.evaluate("testPosts.length"), 1)
                self.assertEqual(page.locator("#id_password").input_value(), "")

    def test_csrf_denial_is_not_treated_as_validation_success(self):
        page = self.mount()
        page.evaluate("testMode='denied'")
        page.locator("#account-invitation-submit").click()
        expect(page.locator("#activation-errors")).to_contain_text("安全校验未通过")
        expect(page.locator("#account-invitation-submit")).to_be_disabled()
        self.assertEqual(page.evaluate("testPosts.length"), 1)

    def test_missing_fragment_never_sends_a_request(self):
        page = self.mount(token="")
        expect(page.locator("#activation-token-error")).to_be_visible()
        expect(page.locator("#account-invitation-submit")).to_be_disabled()
        page.locator("#id_username").press("Enter")
        self.assertEqual(page.evaluate("testPosts"), [])

    def test_error_text_is_not_rendered_as_html(self):
        page = self.mount()
        page.evaluate("testMessage='<img src=x onerror=window.injected=true>'")
        page.locator("#account-invitation-submit").click()
        expect(page.locator("#error-password")).to_have_text(page.evaluate("testMessage"))
        expect(page.locator("#error-password img")).to_have_count(0)
        self.assertIsNone(page.evaluate("window.injected"))

    def test_mobile_labels_and_controls_are_readable(self):
        page = self.mount(width=390)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth-innerWidth"), 1)
        for name in ("username", "password", "confirm_password"):
            control = page.locator("#id_" + name)
            self.assertTrue(control.evaluate("n=>n.labels.length===1 && !!n.getAttribute('aria-describedby')"))
            self.assertGreaterEqual(control.bounding_box()["height"], 44)
        self.assertGreaterEqual(page.locator("#account-invitation-submit").bounding_box()["height"], 44)
        out = Path(os.getenv("HR_VISUAL_ARTIFACT_DIR", "tests/artifacts/hr-visual")) / "ACCOUNT-ACTIVATION-UI-UNIT"
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / "mobile.png"), full_page=True)


if __name__ == "__main__":
    unittest.main()
