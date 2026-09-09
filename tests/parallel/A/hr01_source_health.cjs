'use strict';
// Isolated production-script regression. No Django, MySQL or real API acceptance.
// Run from repository root: node --test tests/parallel/A/hr01_source_health.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const repo = process.env.HR_TEST_ROOT || path.resolve(__dirname, '../../..');
const script = fs.readFileSync(path.join(repo, 'frontend/static/hr/js/pages/todos.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
class Element {
  constructor() { this.dataset = {}; this.attrs = {}; this.listeners = {}; this.innerHTML = ''; this.textContent = ''; this.value = ''; this.isConnected = true; }
  querySelector() { return null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k, fn) { this.listeners[k] = fn; }
  fire(k) { return this.listeners[k]?.(); }
  focus() { this.focused = true; }
}
function boot(summary, list, requestOverride) {
  const ids = ['summary', 'list', 'search', 'severity', 'overdue', 'clear', 'refresh', 'count'];
  const el = Object.fromEntries(ids.map(k => [k, new Element()]));
  const root = new Element();
  root.querySelector = selector => el[selector.replace('#hr-todo-', '')] || null;
  const calls = [];
  const request = (url, options) => {
    calls.push({ url, options });
    if (requestOverride) return requestOverride(url, options);
    const value = url.endsWith('/summary') ? summary : list;
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
  };
  const context = vm.createContext({ document: { readyState: 'complete', querySelector: () => root }, window: { HrApi: { request, apiErrorToMessage: e => e.message } }, console, Intl });
  vm.runInContext(script, context);
  return { el, root, calls, context };
}
const ok = data => ({ ok: true, data });
const empty = status => ok({ status, items: [], pagination: { total: 0 } });
const zeros = status => ok({ status, overdue: 0, today: 0, week: 0 });
for (const status of ['UNAVAILABLE', 'ERROR']) {
  test(`summary ${status} does not render zero counters`, async () => {
    const h = boot(zeros(status), empty(status)); await tick();
    assert.match(h.el.summary.innerHTML, /未用 0 条掩盖读取失败/);
    assert.doesNotMatch(h.el.summary.innerHTML, /hr-summary-number|<b>0<\/b>/);
    assert.match(h.el.list.innerHTML, /待办来源暂不可用/);
    assert.doesNotMatch(h.el.count.textContent, /显示 0/);
  });
}
test('successful empty response is distinct from unavailable', async () => {
  const h = boot(zeros('OK'), empty('OK')); await tick();
  assert.match(h.el.summary.innerHTML, /<b>0<\/b>/);
  assert.match(h.el.list.innerHTML, /当前没有待办事项/);
});
test('partial empty response cannot mean all tasks are complete', async () => {
  const h = boot(zeros('PARTIAL'), empty('PARTIAL')); await tick();
  assert.match(h.el.list.innerHTML, /不能据此判定全部事项已处理/);
  assert.match(h.el.count.textContent, /来源不完整/);
  assert.doesNotMatch(h.el.list.innerHTML, /当前没有待办事项/);
});
test('stale response keeps its warning', async () => {
  const h = boot(zeros('STALE'), empty('STALE')); await tick();
  assert.match(h.el.summary.innerHTML, /来源数据更新延迟/);
  assert.match(h.el.list.innerHTML, /来源数据更新延迟/);
});
test('unknown and negative summary values remain unknown', async () => {
  const h = boot(ok({ status: 'OK', overdue: null, today: -1, week: '0' }), empty('OK')); await tick();
  assert.equal((h.el.summary.innerHTML.match(/<b>—<\/b>/g) || []).length, 3);
  assert.match(h.el.summary.innerHTML, /未将缺项按 0 处理/);
});
test('denied summary does not erase a successful list', async () => {
  const h = boot({ ok: false, status: 403 }, empty('OK')); await tick();
  assert.match(h.el.summary.innerHTML, /概览读取失败/);
  assert.match(h.el.list.innerHTML, /当前没有待办事项/);
});
test('denied list remains failure, not empty success', async () => {
  const h = boot(zeros('OK'), { ok: false, status: 403 }); await tick();
  assert.match(h.el.list.innerHTML, /待办读取失败/);
  assert.doesNotMatch(h.el.list.innerHTML, /当前没有待办事项/);
});
test('network failures are rendered without trusting HTML', async () => {
  const h = boot(new Error('<img src=x onerror=1>'), new Error('<script>bad</script>')); await tick();
  assert.match(h.el.summary.innerHTML, /&lt;img/);
  assert.match(h.el.list.innerHTML, /&lt;script/);
  assert.doesNotMatch(h.el.summary.innerHTML + h.el.list.innerHTML, /<img|<script/);
});
test('malformed list entries fail closed', async () => {
  const h = boot(zeros('OK'), ok({ status: 'OK', items: [null] })); await tick();
  assert.match(h.el.list.innerHTML, /待办读取失败/);
});
test('malformed summary cannot pretend it has counters', async () => {
  const h = boot(ok([]), empty('OK')); await tick();
  assert.match(h.el.summary.innerHTML, /概览读取失败/);
  assert.doesNotMatch(h.el.summary.innerHTML, /hr-summary-number/);
});
test('domain text is escaped; only existing HR destinations are offered', async () => {
  const malicious = '<img src=x onerror="bad()">';
  const h = boot(zeros('PARTIAL'), ok({ status: 'PARTIAL', items: [
    { title: malicious, subjectName: malicious, orgName: malicious, currentStage: malicious, actionLabel: malicious, actionUrl: '/hr/onboarding/prehires/case-1' },
    { title: 'external destination', actionUrl: 'https://invalid.example/' },
  ] })); await tick();
  assert.doesNotMatch(h.el.list.innerHTML, /<img|https:\/\/invalid/);
  assert.match(h.el.list.innerHTML, /&lt;img/);
  assert.match(h.el.list.innerHTML, /href="\/hr\/onboarding\/prehires\/case-1"/);
  assert.match(h.el.list.innerHTML, /仅为已成功读取的数据/);
});
test('filters stay local, preserve request limit, and clear returns focus', async () => {
  const h = boot(zeros('OK'), ok({ status: 'OK', items: [
    { title: '任务甲', severity: 'HIGH', isOverdue: true },
    { title: '任务乙', severity: 'LOW', isOverdue: false },
  ], pagination: { total: 52 } })); await tick();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].options.params.page_size, 50);
  h.el.search.value = '任务甲'; h.el.search.fire('input');
  h.el.overdue.fire('click');
  assert.match(h.el.count.textContent, /显示 1 \/ 2.*来源返回总数 52/);
  h.el.clear.fire('click');
  assert.match(h.el.count.textContent, /显示 2 \/ 2/);
  assert.equal(h.el.search.focused, true);
  assert.equal(h.calls.length, 2);
});
test('concurrent refresh is serialized without duplicate GETs', async () => {
  const pending = [];
  const h = boot(null, null, url => new Promise(resolve => pending.push({ url, resolve })));
  h.el.refresh.fire('click'); h.el.refresh.fire('click');
  assert.equal(h.calls.length, 2);
  for (const p of pending) p.resolve(p.url.endsWith('/summary') ? zeros('OK') : empty('OK'));
  await tick();
  assert.equal(h.el.refresh.getAttribute('aria-busy'), null);
});
test('detached page ignores late responses', async () => {
  const pending = [];
  const h = boot(null, null, url => new Promise(resolve => pending.push({ url, resolve })));
  h.root.isConnected = false;
  const before = h.el.list.innerHTML;
  for (const p of pending) p.resolve(p.url.endsWith('/summary') ? zeros('OK') : empty('OK'));
  await tick(); assert.equal(h.el.list.innerHTML, before);
});
test('mount guard prevents duplicate binding and loading', async () => {
  const h = boot(zeros('OK'), empty('OK')); await tick();
  vm.runInContext(script, h.context); await tick();
  assert.equal(h.calls.length, 2);
});
