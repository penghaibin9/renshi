"""Real Chromium plus production roster JS and controlled HTTP fixtures.

Component-only tests; the separate school_staff_import_browser lane proves DB facts.
"""
import json
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from hr_staff.services.import_workbook import error_workbook, template_workbook
from playwright.sync_api import sync_playwright

OUT = ROOT / "tests/artifacts/school-staff-import-ui"
JOB = "00000000-0000-4000-8000-000000000001"
API = "/api/hr/v1/staff/import"
BASE = "http://import-contract.test"


def require(condition, message):
    if not condition: raise AssertionError(message)


def html(*, allowed=True):
    source = (ROOT / "backend/hr_staff/templates/hr_staff/staff_list.html").read_text()
    content = re.search(r'{% block content %}(.*?){% endblock content %}', source, re.S).group(1)
    content = re.sub(r'{% if not can_import_staff %}(.*?){% endif %}', lambda match: '' if allowed else match[1], content, flags=re.S)
    content = re.sub(r'{{.*?}}|{%.*?%}', '', content, flags=re.S)
    script = re.findall(r'<script>(.*?)</script>', source, re.S)[-1]
    css = '\n'.join((ROOT / ('frontend/static/hr/css/' + name)).read_text() for name in (
        'hr-tokens.css', 'hr-components.css', 'hr-v2.css', 'hr03-staff.css'))
    return '<!doctype html><html lang="zh"><meta charset="utf-8"><style>'+css+'</style><body>'+content+'<script>'+script+'</script></body></html>'


class Fixture:
    def __init__(self, browser, width=1440, *, allowed=True, mode="normal"):
        self.context = browser.new_context(viewport={"width": width, "height": 1000}, accept_downloads=True)
        self.page = self.context.new_page()
        self.mode, self.calls, self.errors = mode, [], []
        self.state = {"jobId": JOB, "status": "READY_TO_COMMIT", "totalRows": 2,
                      "validRows": 1, "failedRows": 1, "pendingRows": 1,
                      "committedRows": 0, "issueCount": 1,
                      "issues": [{"rowNo": 3, "field": "legal_name", "error": "姓名必填"}], "resultRows": []}
        self.allowed = allowed
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.page.route(BASE+'/**', self.route)

    def route(self, route):
        request = route.request
        path = urlsplit(request.url).path
        self.calls.append((request.method, path))
        if path == '/hr/staff/':
            route.fulfill(status=200, content_type='text/html', body=html(allowed=self.allowed)); return
        if path == '/api/hr/v1/staff':
            items = [] if not self.state['committedRows'] else [{"staff_id":"staff-a","staff_no":"IMPORT-001","legal_name":"已建档教师甲","org_name":"教务处","position_name":"EDU-ADMIN-001","current_employment_status":"ACTIVE"}]
            body = {"items":items,"page":1,"total":len(items),"asOf":"2026-09-06","dataBasis":"HR03_AUTHORITY"}
        elif path == API and request.method == 'POST':
            if self.mode == 'invalid-upload':
                route.fulfill(status=400, content_type='application/json', body=json.dumps({'error':{'message':'工作簿结构无效'}})); return
            if self.mode == 'malicious-message':
                self.state['issues'][0]['error'] = '<img src=x onerror="window.injected=1">'
            route.fulfill(status=201, content_type='application/json', body=json.dumps({'data':self.state})); return
        elif path == API + '/template':
            route.fulfill(status=200, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body=template_workbook()); return
        elif path.endswith('/errors'):
            route.fulfill(status=200, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', body=error_workbook([(3,'legal_name','VALIDATION_ERROR','姓名必填')])); return
        elif path == API + '/' + JOB:
            body = {'data':self.state}
        elif path == API + '/' + JOB + '/commit':
            if self.mode == 'network-failure':
                self.finish(); route.abort('failed'); return
            if self.mode == 'segmented':
                self.state.update(status='READY_TO_COMMIT', totalRows=4, validRows=3, committedRows=1, pendingRows=2)
            else: self.finish()
            body = {'data':{**self.state,'committed':self.state['committedRows'],'failed':self.state['failedRows']}}
        else:
            route.fulfill(status=404, body='not-found'); return
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    def finish(self):
        self.state.update(status='PARTIAL_FAILED', committedRows=1, pendingRows=0)

    def open(self, *, resume=False):
        self.page.goto(BASE+'/hr/staff/'+('?importJob='+JOB if resume else ''))
        self.page.locator('#rows td').first.wait_for(state='visible')
        if not resume and self.allowed: self.page.locator('#importToggle').click()

    def preview(self):
        self.page.locator('#importFile').set_input_files({'name':'staff.xlsx','mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','buffer':template_workbook()})
        self.page.locator('#importValidate').click()
        if self.mode == 'invalid-upload':
            self.page.wait_for_function("document.getElementById('importSummary').innerText.includes('未完成')")
        else:
            self.page.wait_for_function("document.getElementById('importConfirmed').disabled === false")

    def commit(self):
        self.page.locator('#importConfirmed').check()
        self.page.locator('#importCommit').click()
        self.page.wait_for_function("document.getElementById('refreshImport').disabled === false")

    def close(self):
        require(not self.errors, 'page errors: '+repr(self.errors))
        self.context.close()


def check_confirmation(f):
    f.open(); f.preview()
    require(f.page.locator('#importCommit').is_disabled(), 'no confirmation guard')
    require(not any(method=='POST' and path.endswith('/commit') for method,path in f.calls), 'preview auto-committed')
    require('第 3 行' in f.page.locator('#importIssues').inner_text(), 'wrong source row')
    f.commit()
    require(f.page.locator('#importCommit').is_disabled(), 'terminal task writable')
    require('IMPORT-001' in f.page.locator('#rows').inner_text(), 'roster not reloaded')


def check_resume(f):
    f.finish(); f.open(resume=True)
    f.page.wait_for_function("document.getElementById('importSummary').innerText.includes('部分行未写入')")
    require(('GET',API+'/'+JOB) in f.calls, 'resume did not read task')
    require(not any(method=='POST' for method,path in f.calls), 'resume wrote data')
    require(f.page.locator('#importCommit').is_disabled(), 'finished resume enabled submit')


def check_network(f):
    f.open(); f.preview(); f.commit()
    f.page.wait_for_function("document.getElementById('notice').innerText.includes('不要重新上传')")
    require(f.page.locator('#importCommit').is_disabled(), 'unknown result can be resubmitted')
    f.page.locator('#refreshImport').click()
    f.page.wait_for_function("document.getElementById('importSummary').innerText.includes('部分行未写入')")
    require(sum(method=='POST' and path.endswith('/commit') for method,path in f.calls)==1, 'extra commit after lost response')


def check_changed_file(f):
    f.open(); f.preview(); f.page.locator('#importConfirmed').check()
    f.page.locator('#importFile').set_input_files({'name':'other.csv','mimeType':'text/csv','buffer':b'legal_name\nAnother'})
    require(f.page.locator('#importCommit').is_disabled(), 'new file inherited old approval')
    require('importJob=' not in f.page.url, 'old task remained attached to new file')


def check_xss(f):
    f.open(); f.preview()
    require(f.page.locator('#importIssues img').count()==0, 'error string became HTML')
    require(f.page.evaluate('window.injected || 0')==0, 'error handler script ran')
    require('<img' in f.page.locator('#importIssues').inner_text(), 'safe error text hidden')


def check_segment(f):
    f.open(); f.preview(); f.commit()
    require('剩余' in f.page.locator('#notice').inner_text(), 'incomplete task described as finished')
    require('继续提交' in f.page.locator('#importCommit').inner_text(), 'missing continuation action')
    require(f.page.locator('#importCommit').is_disabled(), 'next chunk not separately acknowledged')
    f.page.locator('#importConfirmed').check()
    require(f.page.locator('#importCommit').is_enabled(), 'cannot continue remaining rows')


def check_large_upload(f):
    f.open()
    f.page.locator('#importFile').set_input_files({'name':'large.xlsx','mimeType':'application/octet-stream','buffer':b'0'*(5*1024*1024+1)})
    f.page.locator('#importValidate').click()
    require('5 MB' in f.page.locator('#notice').inner_text(), 'missing client size feedback')
    require(('POST',API) not in f.calls, 'oversize upload submitted')


def check_rejected_upload(f):
    f.open(); f.preview()
    require(f.page.locator('#importCommit').is_disabled(), 'invalid workbook can commit')
    require('结构无效' in f.page.locator('#notice').inner_text(), 'server error lost')


def check_viewer(f):
    f.open(resume=True)
    require(f.page.locator('#importToggle').is_disabled(), 'viewer has import action')
    require(('GET',API+'/'+JOB) not in f.calls, 'viewer resumed a privileged task')


def check_downloads(f):
    f.open()
    with f.page.expect_download() as d: f.page.locator('#downloadTemplate').click()
    require(d.value.suggested_filename.endswith('.xlsx'), 'template not XLSX')
    f.preview()
    with f.page.expect_download() as d: f.page.locator('#downloadImportErrors').click()
    require('errors_' in d.value.suggested_filename, 'error workbook download missing')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [(check_confirmation,{}),(check_resume,{}),(check_network,{'mode':'network-failure'}),
             (check_changed_file,{}),(check_xss,{'mode':'malicious-message'}),(check_segment,{'mode':'segmented'}),
             (check_large_upload,{}),(check_rejected_upload,{'mode':'invalid-upload'}),
             (check_viewer,{'allowed':False}),(check_downloads,{})]
    results=[]
    with sync_playwright() as pw:
        options={'headless':True}
        if os.environ.get('CHROMIUM_EXECUTABLE'): options['executable_path']=os.environ['CHROMIUM_EXECUTABLE']
        browser=pw.chromium.launch(**options)
        try:
            for width in (1440,390):
                for check,options in cases:
                    f=Fixture(browser,width,**options)
                    row={'case':check.__name__,'width':width,'result':'PASS'}
                    try:
                        check(f)
                        if check==check_confirmation:
                            f.page.screenshot(path=str(OUT/f'component-{width}.png'),full_page=True)
                        f.close()
                    except Exception as exc:
                        row.update(result='FAIL',error=repr(exc),traceback=traceback.format_exc())
                        f.page.screenshot(path=str(OUT/f'failure-{check.__name__}-{width}.png'),full_page=True)
                        f.context.close()
                    results.append(row)
                    print(row['case'],width,row['result'],flush=True)
        finally: browser.close()
    (OUT/'results.json').write_text(json.dumps({'kind':'controlled-http-component-not-mysql', 'cases':results},ensure_ascii=False,indent=2))
    if any(row['result']=='FAIL' for row in results): raise SystemExit(1)


if __name__=='__main__': main()
