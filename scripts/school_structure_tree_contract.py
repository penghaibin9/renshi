"""Isolated Chromium interaction tests against the actual organizations.js file.

The API is an in-memory fixture. These tests prove client behavior, not Django,
MySQL, tenant authorization, or deployment readiness. No forced clicks are used.
"""
import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

SETUP = r'''() => {
  window.executed = 0;
  window.requestLog = [];
  window.rootPending = null;
  window.childrenPending = null;
  window.deferRoot = false;
  window.deferNextChildren = false;
  window.emptyRoot = false;
  window.branchHasChildren = false;
  window.unsafeText = false;
  window.HrApi = {
    apiErrorToMessage: () => 'request failed',
    request: async (path, options = {}) => {
      window.requestLog.push(path);
      if (path.endsWith('/bootstrap')) {
        return {ok:true,data:{root:window.emptyRoot ? {id:null} :
          {id:1,name:window.unsafeText ? '<img src=x onerror="window.executed=1">学校' : '学校根', childCount:1}}};
      }
      if (path.endsWith('/tree')) {
        const isNested = Number(options.params?.parent_id) === 2;
        const result = {ok:true,data:{nodes:[{id:isNested ? 3 : 2, name:window.unsafeText ? '部门 & <b>中心</b>' : '教务处',
          stable_code:'DEPT',has_children:!isNested && window.branchHasChildren}]}};
        if (window.deferNextChildren) {
          window.deferNextChildren = false;
          return new Promise(resolve => {window.childrenPending = (ok = true) => resolve(ok ? result : {ok:false});});
        }
        return result;
      }
      const isRoot = path.endsWith('/1');
      const result = {ok:true,data:{name:window.unsafeText ? '<svg onload="window.executed=1">文字' :
        (isRoot ? '学校根' : '教务处'), stable_code: '"<code>', org_type:isRoot?'SCHOOL':'OFFICE',
        status:'EFFECTIVE',validity_from:'2026-09-05',child_count:0}};
      if (isRoot && window.deferRoot) {
        window.deferRoot = false;
        return new Promise(resolve => {window.rootPending = (ok = true) => resolve(ok ? result : {ok:false});});
      }
      return result;
    }
  };
}'''


def prepare(browser, width, source, **flags):
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.set_default_timeout(1500)
    page.set_content('<div id="hr-org-tree"></div><main id="hr-org-detail"></main>')
    page.evaluate(SETUP)
    page.evaluate('(flags) => Object.assign(window, flags)', flags)
    page.errors = []
    page.on('pageerror', lambda error: page.errors.append(str(error)))
    page.add_script_tag(content=source)
    page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
    return page


def escape_text(page):
    expect(page.locator('.hr-org-node[data-org-id="2"]')).to_contain_text('部门 & <b>中心</b>')
    expect(page.locator('#hr-org-detail')).to_contain_text('文字')
    assert page.locator('#hr-org-tree img, #hr-org-tree b, #hr-org-detail svg').count() == 0
    assert page.evaluate('window.executed') == 0


def collapse_expand(page):
    child = page.locator('.hr-org-node[data-org-id="2"]')
    child.wait_for(state='visible')
    root = page.locator('.is-root > .hr-org-node__row')
    root.click()
    assert child.count() == 0
    root.click()
    child.wait_for(state='visible')
    assert root.get_attribute('aria-expanded') == 'true'


def stale_detail(page):
    child = page.locator('.hr-org-node[data-org-id="2"] > button')
    child.wait_for(state='visible')
    page.wait_for_function('typeof window.rootPending === "function"')
    child.click()
    expect(page.locator('#hr-org-detail h2')).to_have_text('教务处')
    page.evaluate('async () => {window.rootPending(); await new Promise(requestAnimationFrame);}')
    assert page.locator('.is-selected').get_attribute('data-org-id') == '2'
    assert page.locator('#hr-org-detail h2').inner_text() == '教务处', 'stale root response overwrote selected department'


def cancelled_children(page):
    branch = page.locator('.hr-org-node[data-org-id="2"] > .hr-org-node__row')
    branch.wait_for(state='visible')
    page.evaluate('window.deferNextChildren = true')
    branch.click()
    page.wait_for_function('typeof window.childrenPending === "function"')
    branch.click()
    assert branch.get_attribute('aria-expanded') == 'false'
    page.evaluate('async () => {window.childrenPending(); await new Promise(requestAnimationFrame);}')
    assert page.locator('.hr-org-node[data-org-id="3"]').count() == 0, 'late child request repopulated a collapsed node'
    assert branch.get_attribute('aria-expanded') == 'false'


def empty_school(page):
    expect(page.locator('#hr-org-tree')).to_contain_text('尚未建立学校根组织')
    assert page.evaluate('window.requestLog.length') == 1, 'empty root caused invalid detail/tree requests'


def stale_failed_detail(page):
    child = page.locator('.hr-org-node[data-org-id="2"] > button')
    child.wait_for(state='visible')
    page.wait_for_function('typeof window.rootPending === "function"')
    child.click()
    expect(page.locator('#hr-org-detail h2')).to_have_text('教务处')
    page.evaluate('async () => {window.rootPending(false); await new Promise(requestAnimationFrame);}')
    expect(page.locator('#hr-org-detail h2')).to_have_text('教务处')


def cancelled_failed_children(page):
    branch = page.locator('.hr-org-node[data-org-id="2"] > button')
    branch.wait_for(state='visible')
    page.evaluate('window.deferNextChildren = true')
    branch.click()
    page.wait_for_function('typeof window.childrenPending === "function"')
    branch.click()
    page.evaluate('async () => {window.childrenPending(false); await new Promise(requestAnimationFrame);}')
    assert branch.get_attribute('aria-expanded') == 'false'
    assert page.locator('.hr-org-node[data-org-id="2"] > [data-children]').inner_text() == ''


def root_does_not_change_child_arrow(page):
    branch = page.locator('.hr-org-node[data-org-id="2"] > button')
    branch.wait_for(state='visible')
    # Child remains collapsed when the root is selected; root's arrow search
    # must not borrow a descendant's twisty (root has no twisty of its own).
    page.locator('.is-root > button').click()
    page.locator('.is-root > button').click()
    branch.wait_for(state='visible')
    assert branch.get_attribute('aria-expanded') == 'false'
    assert branch.locator('.hr-org-node__twisty').inner_text() == '▸'


def main():
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--source', default=root / 'frontend/static/hr/js/structure/organizations.js', type=Path)
    parser.add_argument('--output', default=root / 'tests/artifacts/school-bootstrap-contract/tree-contract.json', type=Path)
    parser.add_argument('--chromium', default=os.environ.get('CHROMIUM_EXECUTABLE'))
    args = parser.parse_args()
    source = args.source.read_text(encoding='utf-8')
    results = []
    scenarios = (
        ('escaped-text', escape_text, {'unsafeText': True}),
        ('root-collapse-expand', collapse_expand, {}),
        ('stale-detail-not-applied', stale_detail, {'deferRoot': True}),
        ('cancelled-children-not-applied', cancelled_children, {'branchHasChildren': True}),
        ('empty-school-no-invalid-read', empty_school, {'emptyRoot': True}),
        ('stale-failed-detail-not-applied', stale_failed_detail, {'deferRoot': True}),
        ('cancelled-failed-children-not-applied', cancelled_failed_children, {'branchHasChildren': True}),
        ('root-does-not-change-child-arrow', root_does_not_change_child_arrow, {'branchHasChildren': True}),
    )
    with sync_playwright() as playwright:
        options = {'headless': True}
        if args.chromium:
            options['executable_path'] = args.chromium
        browser = playwright.chromium.launch(**options)
        try:
            for width in (1440, 390):
                for name, fn, flags in scenarios:
                    page = prepare(browser, width, source, **flags)
                    errors = page.errors
                    result = {'width': width, 'scenario': name, 'status': 'PASS'}
                    try:
                        fn(page)
                        assert not errors, repr(errors)
                    except Exception as exc:
                        result['status'] = 'FAIL'
                        result['failure'] = str(exc)[:1500]
                    finally:
                        page.close()
                    results.append(result)
        finally:
            browser.close()
    output = {'scope': 'isolated-frontend-with-fixture-api', 'source': str(args.source),
              'passed': sum(row['status'] == 'PASS' for row in results), 'total': len(results),
              'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output['passed'] == output['total'] else 1)


if __name__ == '__main__':
    main()
