"""Production roster JS in Chromium with in-process responses, never MySQL proof.

Reuse the existing offline fixture. A response race is deterministic: tests
release queued responses explicitly, without changing browser network policy.
"""
import json
import os

from playwright.sync_api import sync_playwright
from school_staff_import_offline_contract import OfflineFixture
from school_staff_import_ui_contract import ROOT, require

OUT = ROOT / "tests/artifacts/school-staff-import-readback"


def ready(fixture):
    fixture.finish()
    fixture.open()
    fixture.page.wait_for_function("document.getElementById('pageInfo').innerText.includes('共 1 人')")
    fixture.page.evaluate("""() => {
      const original = window.fetch;
      window._rosterPending = [];
      window.fetch = (url, options) => {
        if (!String(url).startsWith('/api/v1/hr/staff?')) return original(url, options);
        return new Promise((resolve, reject) => window._rosterPending.push({resolve, reject}));
      };
    }""")


def query(fixture, keyword):
    fixture.page.locator('#keyword').fill(keyword)
    fixture.page.locator('#searchBtn').click()


def release(fixture, index, kind='success', label='LATEST'):
    fixture.page.evaluate("""({index, kind, label}) => {
      const pending = window._rosterPending[index];
      if (kind==='network') { pending.reject(new TypeError('controlled read failure')); return; }
      let body = {items:[{staff_id:label, staff_no:label, legal_name:'测试结果-'+label,
                         current_employment_status:'ACTIVE'}], page:1, total:1,
                  asOf:'2026-09-06', dataBasis:'HR03_AUTHORITY'};
      let status = 200;
      let mime = 'application/json';
      if(kind==='empty') { body.items=[]; body.total=0; }
      if(kind==='invalid') { body.total='<img src=x onerror="window.badRoster=1">'; }
      if(kind==='503') { status=503; body={error:{message:'服务暂不可用'}}; }
      let text = JSON.stringify(body);
      if(kind==='html') { mime='text/html'; text='<html>Login page</html>'; }
      pending.resolve(new Response(text, {status, headers:{'Content-Type':mime}}));
    }""", {'index': index, 'kind': kind, 'label': label})
    # Drain the promise continuations; no arbitrary real-network sleep.
    fixture.page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")


def assert_error(fixture):
    page = fixture.page
    require('名册读取失败' in page.locator('#stats').inner_text(), 'Unknown response was not shown as an error')
    require('IMPORT-001' not in page.locator('#rows').inner_text(), 'Previous staff remained visible after failure')
    require(page.locator('#exportCurrent').is_disabled(), 'Failed query can export stale staff')
    require(page.locator('#prev').is_disabled() and page.locator('#next').is_disabled(), 'Failed query retained paging controls')
    require(page.locator('#asOf').inner_text() == '—', 'Failure retained the old as-of date')
    require('未完成' in page.locator('#pageInfo').inner_text(), 'Failure retained old totals/page')
    require(not fixture.errors, 'Network failure caused an unhandled page error')


def assert_latest(fixture):
    page = fixture.page
    require('LATEST' in page.locator('#rows').inner_text(), 'Current result was replaced')
    require('OLD' not in page.locator('#rows').inner_text(), 'Late response replaced current staff')
    require(page.locator('#exportCurrent').is_enabled(), 'Current valid result cannot be exported')
    require('读取失败' not in page.locator('#stats').inner_text(), 'Stale failure cleared current result')
    require(not fixture.errors, 'Stale failure caused an unhandled page error')


def pending_disables_stale_export(fixture):
    ready(fixture); query(fixture, 'pending')
    require(fixture.page.locator('#exportCurrent').is_disabled(), 'Pending query retained stale export selection')
    require('IMPORT-001' not in fixture.page.locator('#rows').inner_text(), 'Pending query displayed old filter results')
    require(fixture.page.locator('#rows').get_attribute('aria-busy') == 'true', 'Pending query lacks loading state')
    release(fixture, 0)
    assert_latest(fixture)


def network_failure_and_retry(fixture):
    ready(fixture); query(fixture, 'network')
    release(fixture, 0, 'network'); assert_error(fixture)
    query(fixture, 'retry'); release(fixture, 1)
    assert_latest(fixture)


def html_is_not_empty_roster(fixture):
    ready(fixture); query(fixture, 'html')
    release(fixture, 0, 'html'); assert_error(fixture)
    require('暂无符合条件' not in fixture.page.locator('#rows').inner_text(), 'HTML response became empty success')


def invalid_totals_are_not_rendered(fixture):
    ready(fixture); query(fixture, 'invalid')
    release(fixture, 0, 'invalid'); assert_error(fixture)
    require(fixture.page.locator('#stats img').count() == 0, 'Unvalidated totals became markup')
    require(fixture.page.evaluate('window.badRoster || 0') == 0, 'Unvalidated totals executed')


def service_failure_invalidates_summary(fixture):
    ready(fixture); query(fixture, '503')
    release(fixture, 0, '503'); assert_error(fixture)


def late_success_cannot_replace_latest(fixture):
    ready(fixture); query(fixture, 'old'); query(fixture, 'latest')
    release(fixture, 1); release(fixture, 0, label='OLD'); assert_latest(fixture)


def late_error_cannot_clear_latest(fixture):
    ready(fixture); query(fixture, 'old'); query(fixture, 'latest')
    release(fixture, 1); release(fixture, 0, 'network'); assert_latest(fixture)


def old_success_cannot_hide_current_failure(fixture):
    ready(fixture); query(fixture, 'old'); query(fixture, 'latest')
    release(fixture, 1, '503'); release(fixture, 0, label='OLD'); assert_error(fixture)
    require('OLD' not in fixture.page.locator('#rows').inner_text(), 'Old success hid latest failure')


def real_empty_result_remains_explicit(fixture):
    ready(fixture); query(fixture, 'empty'); release(fixture, 0, 'empty')
    require('暂无符合条件' in fixture.page.locator('#rows').inner_text(), 'Valid empty result was rejected')
    require('共 0 人' in fixture.page.locator('#pageInfo').inner_text(), 'Valid zero total missing')
    require(fixture.page.locator('#exportCurrent').is_disabled(), 'Empty result has export selection')
    require('读取失败' not in fixture.page.locator('#stats').inner_text(), 'Valid zero result treated as failure')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = (pending_disables_stale_export, network_failure_and_retry, html_is_not_empty_roster,
              invalid_totals_are_not_rendered, service_failure_invalidates_summary,
              late_success_cannot_replace_latest, late_error_cannot_clear_latest,
              old_success_cannot_hide_current_failure, real_empty_result_remains_explicit)
    results = []
    with sync_playwright() as playwright:
        options = {'headless': True}
        if os.getenv('CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
        browser = playwright.chromium.launch(**options)
        try:
            for width in (1440, 390):
                for check in checks:
                    fixture = OfflineFixture(browser, width)
                    result = {'case': check.__name__, 'width': width, 'result': 'PASS'}
                    try:
                        check(fixture)
                        require(not fixture.errors, 'Unhandled browser error: ' + repr(fixture.errors))
                    except Exception as exc:
                        result.update(result='FAIL', error=repr(exc))
                    finally:
                        fixture.context.close()
                    results.append(result)
                    print(result, flush=True)
        finally:
            browser.close()
    (OUT / 'results.json').write_text(json.dumps({
        'kind': 'offline-production-roster-script-not-http-not-mysql', 'cases': results,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    if any(row['result'] != 'PASS' for row in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
