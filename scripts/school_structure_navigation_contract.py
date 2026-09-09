"""Exercise document-click assertions in Chromium against a loopback fixture.

This tests only browser synchronization, not Django business behavior. The
separate school-structure workflow must still create and read real MySQL facts.
"""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from school_structure_browser import click_document


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/source":
            html = """<a id="link" href="/target" onclick="event.preventDefault();
                history.replaceState({},'',location.href);
                setTimeout(()=>location.assign('/target'),50)">Open</a>
              <a id="bad" href="/unavailable">Unavailable</a>
              <button id="xhr" onclick="history.replaceState({},'',location.href);
                fetch('/target')">Not navigation</button>
              <form method="post" action="/source" onsubmit="event.preventDefault();
                history.replaceState({},'',location.href);setTimeout(()=>this.submit(),50)">
                <input name="value" value="confirmed"><button id="save" type="submit">Save</button>
              </form>"""
        else:
            html = '<main id="destination">Server document</main>'
        self.send_response(503 if self.path == "/unavailable" else 200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(302)
        self.send_header("Location", "/target")
        self.end_headers()


class DocumentNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        options = {"headless": True}
        if os.environ.get("CHROMIUM_EXECUTABLE"):
            options["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]
        cls.browser = cls.playwright.chromium.launch(**options)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.set_default_timeout(5000)
        self.page.goto(self.origin + "/source")

    def test_history_event_cannot_complete_link_wait(self):
        response = click_document(self.page, self.page.locator("#link"), self.origin + "/target")
        self.assertEqual(response.status, 200)
        self.assertTrue(self.page.locator("#destination").is_visible())

    def test_post_redirect_requires_the_actual_final_document(self):
        with self.page.expect_response(lambda response: response.request.method == "POST") as posted:
            response = click_document(self.page, self.page.locator("#save"), self.origin + "/target")
        self.assertEqual(posted.value.status, 302)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.page.url, self.origin + "/target")

    def test_fetch_to_the_same_url_cannot_satisfy_document_proof(self):
        self.page.set_default_timeout(350)
        with self.assertRaises(PlaywrightTimeoutError):
            click_document(self.page, self.page.locator("#xhr"), self.origin + "/target")
        self.assertEqual(self.page.url, self.origin + "/source")

    def test_http_failure_is_not_accepted_as_success(self):
        with self.assertRaisesRegex(AssertionError, "returned 503"):
            click_document(self.page, self.page.locator("#bad"), self.origin + "/unavailable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
