"""Offline DOM contracts: no HTTP navigation, no Django/MySQL evidence.

Uses production HTML/JS and an in-process fetch fixture. Full HTTP and
persistence tests remain separate mandatory steps in the same workflow.
"""
import base64
import json
import os
import re
from types import SimpleNamespace

from playwright.sync_api import sync_playwright
from school_staff_import_ui_contract import (
    ROOT, Fixture, BASE, html, require, check_confirmation, check_network,
    check_xss, check_segment, check_large_upload, check_rejected_upload, check_downloads,
)

OUT = ROOT / "tests/artifacts/school-staff-import-offline"


class OfflineFixture(Fixture):
    def __init__(self, browser, width=1440, *, allowed=True, mode="normal"):
        self.context = browser.new_context(viewport={"width": width, "height": 1000}, accept_downloads=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.mode, self.calls, self.errors = mode, [], []
        self.state = {"jobId": "00000000-0000-4000-8000-000000000001", "status": "READY_TO_COMMIT", "totalRows": 2,
                      "validRows": 1, "failedRows": 1, "pendingRows": 1, "committedRows": 0, "issueCount": 1,
                      "issues": [{"rowNo": 3, "field": "legal_name", "error": "姓名必填"}], "resultRows": []}
        self.allowed = allowed
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.page.expose_binding("_offline_fetch", self.respond)

    def respond(self, source, path, method):
        class Capture:
            request = SimpleNamespace(url=BASE + path, method=method)
            response = None
            def fulfill(self, *, status, body, content_type="text/plain"):
                if isinstance(body, bytes):
                    self.response = {"status": status, "mime": content_type, "base64": base64.b64encode(body).decode()}
                else: self.response = {"status": status, "mime": content_type, "text": body}
            def abort(self, code): self.response = {"abort": code}
        capture = Capture()
        self.route(capture)
        return capture.response

    def open(self, *, resume=False):
        require(not resume, "Deep-link navigation is not covered by this offline test")
        document = html(allowed=self.allowed)
        script = re.findall(r'<script>(.*?)</script>', document, re.S)[-1]
        self.page.set_content(document.replace('<script>'+script+'</script>', ''))
        self.page.evaluate("""() => {
          Object.defineProperty(document, "cookie", {configurable:true, get:()=>""});
          history.replaceState = (state, title, url) => {window._offlineTaskUrl=String(url);};
          window.fetch = async (url, options={}) => {
            const result = await window._offline_fetch(String(url), options.method || 'GET');
            if(result.abort) throw new TypeError('controlled lost response');
            const body = result.base64 ? Uint8Array.from(atob(result.base64), c=>c.charCodeAt(0)) : result.text;
            return new Response(body, {status:result.status,headers:{'Content-Type':result.mime}});
          };
        }""")
        self.page.add_script_tag(content=script)
        self.page.locator('#rows td').first.wait_for(state='visible')
        if self.allowed: self.page.locator('#importToggle').click()


def check_new_file(f):
    f.open(); f.preview(); f.page.locator('#importConfirmed').check()
    f.page.locator('#importFile').set_input_files({'name':'new.csv','mimeType':'text/csv','buffer':b'legal_name\nAnother'})
    require(f.page.locator('#importCommit').is_disabled(), 'new file inherited old confirmation')
    require('importJob=' not in f.page.evaluate('window._offlineTaskUrl'), 'new file kept prior task state')


def check_readonly(f):
    f.open()
    require(f.page.locator('#importToggle').is_disabled(), 'read-only import action enabled')
    require(not any(method=='POST' for method,path in f.calls), 'read-only rendered write')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tests=[(check_confirmation,{}),(check_network,{'mode':'network-failure'}),(check_new_file,{}),
           (check_xss,{'mode':'malicious-message'}),(check_segment,{'mode':'segmented'}),
           (check_large_upload,{}),(check_rejected_upload,{'mode':'invalid-upload'}),
           (check_readonly,{'allowed':False}),(check_downloads,{})]
    results=[]
    with sync_playwright() as pw:
        options={'headless':True}
        if os.environ.get('CHROMIUM_EXECUTABLE'): options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
        browser=pw.chromium.launch(**options)
        try:
            for width in (1440,390):
                for test,options in tests:
                    fixture=OfflineFixture(browser,width,**options)
                    row={'case':test.__name__,'width':width,'result':'PASS'}
                    try:
                        test(fixture)
                        if test==check_confirmation:
                            fixture.page.screenshot(path=str(OUT/f'offline-component-{width}.png'),full_page=True)
                        fixture.close()
                    except Exception as exc:
                        row.update(result='FAIL',error=repr(exc)); fixture.context.close()
                    results.append(row); print(row,flush=True)
        finally: browser.close()
    (OUT/'results.json').write_text(json.dumps({'kind':'offline-dom-with-in-process-fetch-not-http-not-mysql','cases':results},ensure_ascii=False,indent=2))
    if any(row['result']=='FAIL' for row in results): raise SystemExit(1)


if __name__=='__main__': main()
