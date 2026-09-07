"""HR11 UI unit tests with isolated transport, not MySQL/audit acceptance.

Load the complete production script and click actual browser controls. Only the
transport is replaced, to reproduce success, denial and read failures without
manufacturing personnel facts. The existing real-server HR11 gate remains
required for permissions, persistence and per-download audit verification.

Run: python -m unittest tests.visual.hr11_download_lifecycle_tests -v
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "frontend/static/hr/js/pages/hr11-actions.js"
)
FIXTURE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<main class="hr11">
  <a href="https://example.invalid/api/v1/hr/time/leave-evidence/fixture/download"
     title="synthetic-evidence.txt" data-evidence-download>下载证明</a>
  <div data-feedback role="status" aria-live="polite"></div>
  <article data-record-id="fixture">
    <button type="button" data-action="leave-reject">拒绝请假</button>
  </article>
  <dialog data-dialog aria-labelledby="dialog-title">
    <form data-dialog-form method="dialog">
      <h2 id="dialog-title" data-dialog-title></h2>
      <div data-dialog-fields></div>
      <button type="button" data-dialog-close>取消</button>
      <button type="submit" data-dialog-submit>确认办理</button>
    </form>
  </dialog>
</main></html>"""
TRANSPORT = """() => {
  window.hr11Fixture = {calls: [], mode: 'ok', release: null, releases: []};
  window.fetch = async (url, options) => {
    const fixture = window.hr11Fixture;
    fixture.calls.push({url, options});
    if (fixture.mode === 'network-error') throw new TypeError('fixture network failure');
    if (fixture.mode === 'denied') return new Response(
      JSON.stringify({error: {message: '当前账号无权查阅该证明'}}),
      {status: 403, headers: {'Content-Type': 'application/json'}}
    );
    if (fixture.mode === 'body-error') return {
      ok: true, blob: async () => { throw new Error('fixture body read failure'); }
    };
    if (fixture.mode === 'pending') await new Promise(resolve => {
      fixture.release = resolve;
      fixture.releases.push(resolve);
    });
    return new Response('synthetic evidence, UI transport fixture only', {
      status: 200, headers: {'Content-Type': 'text/plain'}
    });
  };
}"""


class Hr11DownloadLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        options = {"headless": True}
        executable = os.getenv("HR_UI_CHROMIUM_EXECUTABLE")
        if executable:
            options["executable_path"] = executable
        self.browser = self.playwright.chromium.launch(**options)
        self.addCleanup(self.browser.close)

    def open_page(self, width=1440, height=1000):
        context = self.browser.new_context(
            viewport={"width": width, "height": height}, accept_downloads=True
        )
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.set_content(FIXTURE)
        page.evaluate(TRANSPORT)
        self.page_errors = []
        self.downloads = []
        page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        page.on("download", lambda download: self.downloads.append(download))
        page.add_script_tag(path=str(SCRIPT))
        return page

    def open_download(self, page, reason):
        page.get_by_role("link", name="下载证明", exact=True).click()
        dialog = page.locator("[data-dialog]")
        expect(dialog).to_be_visible()
        expect(dialog.locator("[data-dialog-submit]")).to_be_enabled()
        dialog.locator("[name='reason']").fill(reason)
        return dialog

    def finish_download(self, page, dialog):
        with page.expect_download() as received:
            dialog.locator("[data-dialog-submit]").click()
        self.assertEqual(received.value.suggested_filename, "synthetic-evidence.txt")
        expect(dialog).not_to_be_visible()
        expect(page.locator("[data-dialog-submit]")).to_be_enabled()
        self.assertIsNone(
            page.locator("[data-evidence-download]").get_attribute("aria-disabled")
        )
        expect(page.locator("[data-feedback]")).to_contain_text("证明已下载")

    def assert_request(self, request, reason):
        self.assertEqual(request["options"]["credentials"], "same-origin")
        self.assertNotIn("?", request["url"])
        self.assertEqual(
            request["options"]["headers"]["X-HR-Access-Reason"], reason
        )
        self.assertEqual(
            request["options"]["headers"]["X-Requested-With"], "XMLHttpRequest"
        )

    def test_repeated_downloads_and_next_leave_dialog_on_desktop_and_mobile(self):
        for mode, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
            with self.subTest(mode=mode):
                page = self.open_page(width, height)
                reasons = ("首次核对本次请假材料", "复核已批准事项的证明依据")
                for reason in reasons:
                    dialog = self.open_download(page, reason)
                    self.finish_download(page, dialog)
                calls = page.evaluate("window.hr11Fixture.calls")
                self.assertEqual(len(calls), 2)
                for request, reason in zip(calls, reasons):
                    self.assert_request(request, reason)
                self.assertEqual(len(self.downloads), 2)
                page.get_by_role("button", name="拒绝请假", exact=True).click()
                expect(page.locator("[data-dialog]")).to_be_visible()
                expect(page.locator("[data-dialog-submit]")).to_be_enabled()
                expect(page.locator("[name='reason']")).to_have_value("")
                self.assertEqual(self.page_errors, [])
                artifact_dir = os.getenv("HR_VISUAL_ARTIFACT_DIR")
                if artifact_dir:
                    destination = Path(artifact_dir) / "HR11-DOWNLOAD-UI-UNIT"
                    destination.mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(destination / f"{mode}-next-dialog-enabled.png")
                    )
                page.close()

    def assert_failure_retry(self, mode, message):
        page = self.open_page()
        page.evaluate("mode => { window.hr11Fixture.mode = mode; }", mode)
        reason = "保留查阅事由供有权人员核验"
        dialog = self.open_download(page, reason)
        dialog.locator("[data-dialog-submit]").click()
        expect(page.locator("[data-feedback].is-error")).to_contain_text(message)
        expect(dialog).to_be_visible()
        expect(dialog.locator("[name='reason']")).to_have_value(reason)
        expect(dialog.locator("[data-dialog-submit]")).to_be_enabled()
        self.assertIsNone(
            page.locator("[data-evidence-download]").get_attribute("aria-disabled")
        )
        self.assertEqual(self.downloads, [])
        page.evaluate("window.hr11Fixture.mode = 'ok'")
        self.finish_download(page, dialog)
        calls = page.evaluate("window.hr11Fixture.calls")
        self.assertEqual(len(calls), 2)
        for request in calls:
            self.assert_request(request, reason)
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(self.page_errors, [])

    def test_denial_retains_reason_and_allows_retry(self):
        self.assert_failure_retry("denied", "当前账号无权查阅该证明")

    def test_network_failure_releases_controls_for_retry(self):
        self.assert_failure_retry("network-error", "fixture network failure")

    def test_body_read_failure_releases_controls_for_retry(self):
        self.assert_failure_retry("body-error", "fixture body read failure")

    def test_whitespace_reason_never_requests_or_downloads_evidence(self):
        page = self.open_page()
        dialog = self.open_download(page, "   ")
        dialog.locator("[data-dialog-submit]").click()
        expect(page.locator("[data-feedback].is-error")).to_contain_text(
            "必须填写查阅事由"
        )
        expect(dialog).to_be_visible()
        expect(dialog.locator("[data-dialog-submit]")).to_be_enabled()
        self.assertEqual(page.evaluate("window.hr11Fixture.calls"), [])
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.page_errors, [])

    def test_pending_download_keeps_confirmation_disabled_until_body_arrives(self):
        page = self.open_page()
        page.evaluate("window.hr11Fixture.mode = 'pending'")
        dialog = self.open_download(page, "核对本次合成请假证明")
        dialog.locator("[data-dialog-submit]").click()
        expect(dialog.locator("[data-dialog-submit]")).to_be_disabled()
        expect(page.locator("[data-evidence-download]")).to_have_attribute(
            "aria-disabled", "true"
        )
        self.assertEqual(len(page.evaluate("window.hr11Fixture.calls")), 1)
        self.assertEqual(self.downloads, [])
        with page.expect_download():
            page.evaluate("window.hr11Fixture.release()")
        expect(dialog).not_to_be_visible()
        expect(page.locator("[data-dialog-submit]")).to_be_enabled()
        self.assertIsNone(
            page.locator("[data-evidence-download]").get_attribute("aria-disabled")
        )
        self.assertEqual(len(page.evaluate("window.hr11Fixture.calls")), 1)
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(self.page_errors, [])


    def test_dismissed_download_does_not_unlock_or_close_newer_pending_dialog(self):
        for dismissal in ("cancel-button", "escape"):
            with self.subTest(dismissal=dismissal):
                page = self.open_page()
                # A second synthetic link belongs only to this UI fixture.
                page.locator(".hr11").evaluate(
                    """root => {
                      const link = root.querySelector('[data-evidence-download]').cloneNode(true);
                      link.href = link.href.replace('/fixture/', '/second-fixture/');
                      link.textContent = '下载另一份证明';
                      root.prepend(link);
                    }"""
                )
                page.evaluate("window.hr11Fixture.mode = 'pending'")
                dialog = self.open_download(page, "第一份证明的查阅事由")
                dialog.locator("[data-dialog-submit]").click()
                expect(dialog.locator("[data-dialog-submit]")).to_be_disabled()
                if dismissal == "cancel-button":
                    dialog.get_by_role("button", name="取消", exact=True).click()
                else:
                    page.keyboard.press("Escape")
                expect(dialog).not_to_be_visible()

                # aria-disabled is advisory on anchors; keyboard activation must
                # not send another request while the original read is pending.
                page.get_by_role("link", name="下载证明", exact=True).press("Enter")
                expect(dialog).not_to_be_visible()
                self.assertEqual(len(page.evaluate("window.hr11Fixture.calls")), 1)

                page.get_by_role("link", name="下载另一份证明", exact=True).click()
                expect(dialog).to_be_visible()
                expect(dialog.locator("[data-dialog-submit]")).to_be_enabled()
                dialog.locator("[name='reason']").fill("第二份证明的独立查阅事由")
                dialog.locator("[data-dialog-submit]").click()
                expect(dialog.locator("[data-dialog-submit]")).to_be_disabled()
                self.assertEqual(len(page.evaluate("window.hr11Fixture.calls")), 2)

                with page.expect_download():
                    page.evaluate("window.hr11Fixture.releases[0]()")
                expect(dialog).to_be_visible()
                expect(dialog.locator("[data-dialog-submit]")).to_be_disabled()
                expect(dialog.locator("[name='reason']")).to_have_value(
                    "第二份证明的独立查阅事由"
                )
                expect(page.locator("[data-feedback]")).to_contain_text("正在校验学校")
                expect(
                    page.get_by_role("link", name="下载另一份证明", exact=True)
                ).to_have_attribute("aria-disabled", "true")
                with page.expect_download():
                    page.evaluate("window.hr11Fixture.releases[1]()")
                expect(dialog).not_to_be_visible()
                expect(page.locator("[data-dialog-submit]")).to_be_enabled()
                self.assertEqual(len(self.downloads), 2)
                self.assertEqual(len(page.evaluate("window.hr11Fixture.calls")), 2)
                self.assertEqual(self.page_errors, [])
                page.close()


if __name__ == "__main__":
    unittest.main()
