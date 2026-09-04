/* HR14 岗位聘任 — real workflow bindings for the unified V2 workspace. */
(() => {
  'use strict';

  const root = document.querySelector("[data-module='HR14']");
  if (!root || root.dataset.hr14WorkflowsBooted === 'true') return;
  root.dataset.hr14WorkflowsBooted = 'true';

  const section = root.dataset.section || 'overview';
  const permissions = {
    apply: root.dataset.canApply === 'true',
    manage: root.dataset.canManage === 'true',
    review: root.dataset.canReview === 'true',
    publicity: root.dataset.canPublicity === 'true',
    decide: root.dataset.canDecide === 'true',
    effect: root.dataset.canEffect === 'true',
    term: root.dataset.canTerm === 'true',
    factCorrect: root.dataset.canFactCorrect === 'true',
  };
  const stateLabels = {
    DRAFT: '草稿', CONFIGURING: '配置中', PUBLISHED: '已发布', APPLICATION_OPEN: '申报开放',
    APPLICATION_CLOSED: '申报已截止', ELIGIBILITY_REVIEW: '资格审查中',
    REVIEW: '评议中', SUBMITTED: '已提交', RETURNED: '退回补正',
    ELIGIBLE: '资格通过', REJECTED: '未通过', UNDER_REVIEW: '评议中',
    PROPOSED: '拟聘', PUBLICITY: '公示中', EFFECTIVE: '已生效',
    OPEN: '公示中', CLOSED: '已关闭', CANCELLED: '已取消',
    RECEIVED: '已登记', NOT_UPHELD: '不成立', UPHELD: '成立', WITHDRAWN: '已撤回',
    ACTIVE: '有效', EXPIRING: '临期', RENEWAL_IN_PROGRESS: '续聘中',
    EXPIRED: '已到期', SUPERSEDED: '已被后继记录替代', READY: '待决定',
    APPROVED: '已批准，待生效', APPLIED: '已正式生效',
    REVIEW_REQUIRED: '待审议', REAPPOINTMENT_REQUIRED: '需重新竞聘',
    SELECTED: '入选', WAITLISTED: '候补', NOT_SELECTED: '未入选',
    EFFECT_PENDING: '生效待重试', ENDED: '已终止',
  };
  const routeLabels = {
    DIRECT_RENEWAL: '直接续聘', TERM_ASSESSMENT: '聘期考核后续聘',
    REAPPOINTMENT: '重新竞聘',
  };
  const changeLabels = {
    PROMOTION: '高聘 / 晋升', DOWNGRADE: '低聘', TRANSFER: '转岗',
    TERMINATION: '解聘 / 终止', CORRECTION: '正式纠错',
  };

  let snapshot = null;
  let setupSnapshot = {policies: [], positions: [], openTargets: [], applicants: []};
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const csrf = () => (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || '');
  const label = (value) => stateLabels[value] || '状态待确认';
  const dateTime = (value) => value ? String(value).slice(0, 16).replace('T', ' ') : '—';
  const localInput = (date) => {
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };

  async function request(url, body = {}, method = 'POST', extraHeaders = {}) {
    const response = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
        'X-Requested-With': 'XMLHttpRequest',
        ...extraHeaders,
      },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const serverMessage = payload?.error?.message;
      const error = new Error(serverMessage && /[\u3400-\u9fff]/.test(serverMessage) ? serverMessage : '办理失败，请核对当前状态后重试');
      error.code = payload?.error?.code || `HTTP_${response.status}`;
      error.data = payload?.data || null;
      throw error;
    }
    return payload;
  }

  async function reload() {
    const options = {credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}};
    const [response, setupResponse] = await Promise.all([
      fetch('/api/v1/hr/appointments/dashboard/', options),
      fetch('/api/v1/hr/appointments/setup-options/', options),
    ]);
    if (!response.ok) throw new Error(`数据刷新失败（状态码 ${response.status}）`);
    snapshot = await response.json();
    if (setupResponse.ok) setupSnapshot = (await setupResponse.json()).data || setupSnapshot;
    renderSection();
  }

  function host() {
    const column = document.querySelector('.hr14-layout > div');
    if (!column) return null;
    let node = document.getElementById('hr14-workflow');
    if (!node) {
      node = document.createElement('article');
      node.id = 'hr14-workflow';
      node.className = 'hr14-card hr14-workflow';
      column.appendChild(node);
    }
    return node;
  }

  function permissionNotice(text) {
    return `<div class="hr14-workflow__notice" data-tone="warning">${esc(text)}</div>`;
  }

  function setMessage(scope, text, bad = false) {
    const target = typeof scope === 'string' ? document.querySelector(scope) : scope;
    if (!target) return;
    let message = target.querySelector('.hr14-form-message');
    if (!message) {
      message = document.createElement('div');
      message.className = 'hr14-form-message';
      target.appendChild(message);
    }
    message.dataset.tone = bad ? 'danger' : 'success';
    message.textContent = text;
  }

  async function run(button, scope, action) {
    button.disabled = true;
    setMessage(scope, '正在提交…');
    try {
      await action();
      setMessage(scope, '已保存，正在刷新真实状态');
      await reload();
    } catch (error) {
      setMessage(scope, `${error.code ? `${error.code}：` : ''}${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  }

  function renderCompetition() {
    const target = host();
    if (!target) return;
    const rows = snapshot.recentBatches || [];
    const policies = setupSnapshot.policies || [];
    const positions = setupSnapshot.positions || [];
    const drafts = rows.filter((item) => ['DRAFT', 'CONFIGURING'].includes(item.status));
    const now = new Date();
    target.innerHTML = `
      <div class="hr14-workflow__head"><div><h2>制度、额度与竞聘批次启动</h2><p>从已生效 HR02 岗位和当前 HR03 人群形成冻结快照；发布门槛不会在浏览器里跳过。</p></div></div>
      ${permissions.manage ? '' : permissionNotice('当前账号只有查看权限，不能推进竞聘批次。')}
      ${permissions.manage ? `<div class="hr14-workflow-grid">
        <form id="hr14-policy-create" class="hr14-workflow-form compact">
          <h3>新建聘任制度版本</h3>
          <label><span>制度代码</span><input name="policyCode" required placeholder="APPOINT_2026"></label>
          <label><span>制度名称</span><input name="name" required placeholder="2026 岗位聘任办法"></label>
          <label><span>岗位类别</span><input name="positionCategory" placeholder="可留空"></label>
          <label><span>岗位等级</span><input name="levelCode" placeholder="可留空"></label>
          <label><span>生效日期</span><input name="effectiveFrom" type="date" required></label>
          <label><span>失效日期</span><input name="effectiveTo" type="date"></label>
          <button type="submit">发布制度版本</button>
        </form>
        <form id="hr14-batch-create" class="hr14-workflow-form compact">
          <h3>新建竞聘批次</h3>
          <label><span>批次编号</span><input name="batchNo" required placeholder="BATCH_2026_01"></label>
          <label><span>批次名称</span><input name="name" required></label>
          <label class="wide"><span>聘任制度</span><select name="policyVersionId" required>${policies.length ? policies.map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('') : '<option value="">请先建立制度</option>'}</select></label>
          <label><span>申报开始</span><input name="applicationFrom" type="datetime-local" value="${localInput(now)}" required></label>
          <label><span>申报结束</span><input name="applicationTo" type="datetime-local" value="${localInput(new Date(now.getTime() + 7 * 86400000))}" required></label>
          <label><span>公示开始</span><input name="publicityFrom" type="datetime-local" value="${localInput(new Date(now.getTime() + 10 * 86400000))}" required></label>
          <label><span>公示结束</span><input name="publicityTo" type="datetime-local" value="${localInput(new Date(now.getTime() + 15 * 86400000))}" required></label>
          <button type="submit">保存草稿批次</button>
        </form>
        <form id="hr14-supply-quota" class="hr14-workflow-form compact">
          <h3>冻结岗位供给与额度</h3>
          <label class="wide"><span>草稿批次</span><select name="batchId" required>${drafts.length ? drafts.map((item) => `<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.batch_no)}</option>`).join('') : '<option value="">暂无草稿批次</option>'}</select></label>
          <label class="wide"><span>HR02 可用岗位</span><select name="positionId" required>${positions.length ? positions.map((item) => `<option value="${esc(item.value)}" data-max="${esc(item.availableCount)}">${esc(item.label)}</option>`).join('') : '<option value="">暂无可用岗位</option>'}</select></label>
          <label><span>本批次额度</span><input name="authorized" type="number" min="1" value="1" required></label>
          <div class="hr14-workflow__notice wide">额度不能超过 HR02 当前可用量；保存后会形成不可随意改写的岗位供给快照和额度池。</div>
          <button type="submit">保存供给与额度</button>
        </form>
      </div>` : ''}
      <h3 class="hr14-workflow-subtitle">批次状态推进</h3>
      <div class="hr14-workflow-list">${rows.length ? rows.map((item) => {
        const actions = [];
        if (['DRAFT', 'CONFIGURING'].includes(item.status)) actions.push(['freeze', '冻结候选范围'], ['publish', '发布批次']);
        if (item.status === 'PUBLISHED') actions.push(['open', '开放申报']);
        if (item.status === 'APPLICATION_OPEN') actions.push(['close', '截止申报']);
        if (item.status === 'APPLICATION_CLOSED') actions.push(['eligibility', '开始资格审查']);
        if (item.status === 'ELIGIBILITY_REVIEW') actions.push(['review', '开始评议']);
        return `<div class="hr14-workflow-row"><div><b>${esc(item.name || item.batch_no)}</b><small>${esc(item.batch_no)} · ${dateTime(item.application_from)} 至 ${dateTime(item.application_to)}</small></div><span class="hr14-badge">${esc(label(item.status))}</span>${actions.length && permissions.manage ? `<div class="hr14-workflow-actions">${actions.map(([action, text]) => `<button type="button" data-batch-action="${action}" data-record="${esc(item.id)}">${text}</button>`).join('')}</div>` : '<small class="hr14-workflow-row__hint">当前状态没有可执行动作</small>'}</div>`;
      }).join('') : '<div class="hr14-empty">当前学校尚无竞聘批次。批次创建需要从受控制度与岗位范围发起，本页面不提供内部编号输入。</div>'}</div>`;

    const bind = (id, build) => {
      const form = document.getElementById(id);
      form?.addEventListener('submit', (event) => {
        event.preventDefault();
        const values = new FormData(form);
        run(form.querySelector('button'), form, () => build(values));
      });
    };
    bind('hr14-policy-create', (values) => request('/api/v1/hr/appointments/policies/', Object.fromEntries(values.entries())));
    bind('hr14-batch-create', (values) => {
      if (!values.get('policyVersionId')) throw new Error('请先建立聘任制度版本');
      return request('/api/v1/hr/appointments/batches/', {
        batchNo: values.get('batchNo'), name: values.get('name'), policyVersionId: values.get('policyVersionId'),
        applicationFrom: new Date(values.get('applicationFrom')).toISOString(), applicationTo: new Date(values.get('applicationTo')).toISOString(),
        publicityFrom: new Date(values.get('publicityFrom')).toISOString(), publicityTo: new Date(values.get('publicityTo')).toISOString(),
        targetCategories: [], targetLevels: [],
      });
    });
    bind('hr14-supply-quota', (values) => {
      if (!values.get('batchId') || !values.get('positionId')) throw new Error('请选择草稿批次和可用岗位');
      return request(`/api/v1/hr/appointments/batches/${encodeURIComponent(values.get('batchId'))}/supply-quota/`, {
        positionInstanceId: Number(values.get('positionId')), authorized: Number(values.get('authorized')),
      });
    });

    target.querySelectorAll('[data-batch-action]').forEach((button) => button.addEventListener('click', () => {
      const routes = {
        freeze: 'population/freeze/', publish: 'publish/', open: 'applications/open/',
        close: 'applications/close/', eligibility: 'eligibility/start/', review: 'review/start/',
      };
      const scope = button.closest('.hr14-workflow-row');
      run(button, scope, () => request(`/api/v1/hr/appointments/batches/${encodeURIComponent(button.dataset.record)}/${routes[button.dataset.batchAction]}`, button.dataset.batchAction === 'freeze' ? {asOfDate: new Date().toISOString().slice(0, 10)} : {}));
    }));
  }

  function renderApplications() {
    const target = host();
    if (!target) return;
    const rows = snapshot.recentApplications || [];
    const targets = setupSnapshot.openTargets || [];
    const applicants = setupSnapshot.applicants || [];
    target.innerHTML = `
      <div class="hr14-workflow__head"><div><h2>申报案件办理</h2><p>提交、退回、资格结论、进入评议和撤回均保留真实案件状态，不把草稿当成已提交。</p></div></div>
      ${permissions.apply ? `<form id="hr14-application-create" class="hr14-workflow-form">
        <label><span>申报编号</span><input name="caseNo" required placeholder="APP_2026_001"></label>
        <label><span>申报人</span><select name="personId" required>${applicants.length ? applicants.map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('') : '<option value="">开放批次中没有可申报人员</option>'}</select></label>
        <label class="wide"><span>开放批次与岗位</span><select name="target" required>${targets.length ? targets.map((item, index) => `<option value="${index}">${esc(item.label)}</option>`).join('') : '<option value="">当前没有开放申报的岗位</option>'}</select></label>
        <button type="submit">创建申报草稿</button>
      </form>` : permissionNotice('当前账号没有岗位竞聘申报权限。')}
      <div class="hr14-workflow-list">${rows.length ? rows.map((item) => {
        const actions = [];
        if (['DRAFT', 'RETURNED'].includes(item.status) && permissions.apply) actions.push(['submit', '提交申报']);
        if (['DRAFT', 'RETURNED', 'SUBMITTED'].includes(item.status) && permissions.apply) actions.push(['withdraw', '撤回']);
        if (item.status === 'SUBMITTED' && permissions.manage) actions.push(['return', '退回补正'], ['eligibility/pass', '资格通过'], ['eligibility/reject', '资格不通过']);
        if (item.status === 'ELIGIBLE' && permissions.review) actions.push(['review/start', '进入评议']);
        return `<div class="hr14-workflow-row"><div><b>${esc(item.case_no)}</b><small>${esc(item.batch_no)} · 申报等级 ${esc(item.requested_level_code || '未填写')}</small></div><span class="hr14-badge">${esc(label(item.status))}</span>${actions.length ? `<div class="hr14-workflow-actions">${actions.map(([action, text]) => `<button type="button" data-case-action="${action}" data-record="${esc(item.id)}">${text}</button>`).join('')}</div>` : '<small class="hr14-workflow-row__hint">当前账号或案件状态没有可执行动作</small>'}</div>`;
      }).join('') : '<div class="hr14-empty">当前学校尚无竞聘申报。</div>'}</div>`;
    const createForm = document.getElementById('hr14-application-create');
    createForm?.addEventListener('submit', (event) => {
      event.preventDefault();
      const values = new FormData(createForm);
      const selected = targets[Number(values.get('target'))];
      if (!selected || !values.get('personId')) return setMessage(createForm, '请选择开放岗位和申报人', true);
      run(createForm.querySelector('button'), createForm, () => request('/api/v1/hr/appointments/applications/', {
        caseNo: values.get('caseNo'), personId: values.get('personId'),
        policyVersionId: selected.policyVersionId, positionInstanceId: selected.positionInstanceId,
        batchNo: selected.batchNo, requestedLevelCode: selected.levelCode || '',
      }));
    });
    target.querySelectorAll('[data-case-action]').forEach((button) => button.addEventListener('click', () => {
      const scope = button.closest('.hr14-workflow-row');
      run(button, scope, () => request(`/api/v1/hr/appointments/applications/${encodeURIComponent(button.dataset.record)}/${button.dataset.caseAction}/`));
    }));
  }

  function renderRanking() {
    const target = host();
    if (!target) return;
    const cases = (snapshot.recentApplications || []).filter((item) => item.status === 'UNDER_REVIEW');
    const rows = snapshot.recentRankings || [];
    target.innerHTML = `
      <div class="hr14-workflow__head"><div><h2>形成评议排序</h2><p>只有已进入评议的申报可形成排序；入选、候补和未入选作为独立事实保存。</p></div></div>
      ${permissions.review ? `<form id="hr14-ranking-form" class="hr14-workflow-form">
        <label class="wide"><span>待评议申报</span><select name="caseId" required>${cases.length ? cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(item.batch_no)} · ${esc(item.requested_level_code || '未分级')}</option>`).join('') : '<option value="">当前没有待评议申报</option>'}</select></label>
        <label><span>排序结果编号</span><input name="rankingNo" required placeholder="例如：PX-2026-001"></label>
        <label><span>总分</span><input name="score" type="number" step="0.01" min="0" required></label>
        <label><span>名次</span><input name="rank" type="number" min="1" required></label>
        <label><span>排序结论</span><select name="outcome"><option value="SELECTED">入选</option><option value="WAITLISTED">候补</option><option value="NOT_SELECTED">未入选</option></select></label>
        <button type="submit">固化排序结果</button>
      </form>` : permissionNotice('当前账号没有评议排序权限。')}
      <h3 class="hr14-workflow-subtitle">已固化排序</h3>
      <div class="hr14-workflow-list">${rows.length ? rows.map((item) => `<div class="hr14-workflow-row"><div><b>${esc(item.ranking_no)}</b><small>${esc(item.batch_no)} · 第 ${esc(item.rank_no)} 名 · 得分 ${esc(item.total_score)}</small></div><span class="hr14-badge">${esc(label(item.outcome))}</span><small>${esc(String(item.finalized_at || '').slice(0, 10))}</small></div>`).join('') : '<div class="hr14-empty">当前尚无已固化排序结果。</div>'}</div>`;
    const form = document.getElementById('hr14-ranking-form');
    form?.addEventListener('submit', (event) => {
      event.preventDefault();
      const values = new FormData(form);
      const button = form.querySelector('button');
      if (!values.get('caseId')) return setMessage(form, '当前没有可办理的评议申报', true);
      run(button, form, () => request(`/api/v1/hr/appointments/applications/${encodeURIComponent(values.get('caseId'))}/ranking-result/`, {
        rankingNo: values.get('rankingNo'), totalScore: values.get('score'),
        rankNo: Number(values.get('rank')), outcome: values.get('outcome'),
        scoreSnapshot: {source: 'HR14 评议工作区'},
      }));
    });
  }

  function renderPublicity() {
    const target = host();
    if (!target) return;
    const cases = (snapshot.recentApplications || []).filter((item) => item.status === 'PROPOSED');
    const rankings = (snapshot.recentRankings || []).filter((item) => item.outcome === 'SELECTED');
    const publicities = snapshot.recentPublicities || [];
    const openPublicities = publicities.filter((item) => item.status === 'OPEN');
    const objections = snapshot.recentObjections || [];
    const pendingObjections = objections.filter((item) => ['RECEIVED', 'UNDER_REVIEW'].includes(item.status));
    const caseLabel = (id) => (snapshot.recentApplications || []).find((item) => String(item.id) === String(id))?.case_no || '关联申报';
    const publicityLabel = (id) => publicities.find((item) => String(item.id) === String(id))?.publicity_no || '关联公示';
    const now = new Date();

    target.innerHTML = `
      <div class="hr14-workflow__head"><div><h2>拟聘公示与异议闭环</h2><p>只有入选结果可发起公示；公示期结束且异议全部处理后，才允许进入正式聘任。</p></div></div>
      ${permissions.publicity ? `<div class="hr14-workflow-grid">
        <form id="hr14-publicity-open" class="hr14-workflow-form compact">
          <h3>发起拟聘公示</h3>
          <label class="wide"><span>拟聘申报</span><select name="caseId" required>${cases.length ? cases.map((item) => `<option value="${esc(item.id)}">${esc(item.case_no)} · ${esc(item.batch_no)} · ${esc(item.requested_level_code || '未分级')}</option>`).join('') : '<option value="">暂无待公示申报</option>'}</select></label>
          <label class="wide"><span>入选排序</span><select name="rankingId" required>${rankings.length ? rankings.map((item) => `<option value="${esc(item.id)}">${esc(item.ranking_no)} · 第 ${esc(item.rank_no)} 名</option>`).join('') : '<option value="">暂无入选排序</option>'}</select></label>
          <label><span>公示编号</span><input name="publicityNo" required placeholder="例如：GS-2026-001"></label>
          <label><span>开始时间</span><input name="startAt" type="datetime-local" value="${localInput(now)}" required></label>
          <label><span>结束时间</span><input name="endAt" type="datetime-local" value="${localInput(new Date(now.getTime() + 5 * 86400000))}" required></label>
          <button type="submit">发起公示</button>
        </form>
        <form id="hr14-objection-open" class="hr14-workflow-form compact">
          <h3>登记公示异议</h3>
          <label class="wide"><span>开放中的公示</span><select name="publicityId" required>${openPublicities.length ? openPublicities.map((item) => `<option value="${esc(item.id)}">${esc(item.publicity_no)} · ${esc(caseLabel(item.application_case_id))}</option>`).join('') : '<option value="">暂无开放中的公示</option>'}</select></label>
          <label><span>异议编号</span><input name="objectionNo" required placeholder="例如：YY-2026-001"></label>
          <label><span>提交人</span><input name="submitter" placeholder="姓名或登记号"></label>
          <label class="wide"><span>异议摘要</span><textarea name="summary" required placeholder="说明需要复核的事实"></textarea></label>
          <button type="submit">登记异议</button>
        </form>
        <form id="hr14-objection-resolve" class="hr14-workflow-form compact">
          <h3>处理异议</h3>
          <label class="wide"><span>待处理异议</span><select name="objectionId" required>${pendingObjections.length ? pendingObjections.map((item) => `<option value="${esc(item.id)}">${esc(item.objection_no)} · ${esc(publicityLabel(item.publicity_id))}</option>`).join('') : '<option value="">暂无待处理异议</option>'}</select></label>
          <label><span>处理结论</span><select name="outcome"><option value="NOT_UPHELD">不成立</option><option value="UPHELD">成立</option><option value="WITHDRAWN">撤回</option></select></label>
          <label class="wide"><span>处理依据</span><textarea name="note" required placeholder="填写复核依据和结论"></textarea></label>
          <button type="submit">保存处理结论</button>
        </form>
        <form id="hr14-publicity-close" class="hr14-workflow-form compact">
          <h3>关闭公示</h3>
          <label class="wide"><span>待关闭公示</span><select name="publicityId" required>${openPublicities.length ? openPublicities.map((item) => `<option value="${esc(item.id)}">${esc(item.publicity_no)} · 截止 ${esc(dateTime(item.end_at))}</option>`).join('') : '<option value="">暂无开放中的公示</option>'}</select></label>
          <div class="hr14-workflow__notice wide">系统会再次校验公示期和异议状态，条件不满足时不会关闭。</div>
          <button type="submit">校验并关闭</button>
        </form>
      </div>` : permissionNotice('当前账号没有公示与异议办理权限。')}
      <h3 class="hr14-workflow-subtitle">公示记录</h3>
      <div class="hr14-workflow-list">${publicities.length ? publicities.map((item) => `<div class="hr14-workflow-row"><div><b>${esc(item.publicity_no)}</b><small>${esc(caseLabel(item.application_case_id))} · ${dateTime(item.start_at)} 至 ${dateTime(item.end_at)}</small></div><span class="hr14-badge">${esc(label(item.status))}</span><small>${esc(String(item.closed_at || item.opened_at || '').slice(0, 10))}</small></div>`).join('') : '<div class="hr14-empty">当前没有公示记录。</div>'}</div>
      <h3 class="hr14-workflow-subtitle">异议记录</h3>
      <div class="hr14-workflow-list">${objections.length ? objections.map((item) => `<div class="hr14-workflow-row"><div><b>${esc(item.objection_no)}</b><small>${esc(publicityLabel(item.publicity_id))} · ${esc(item.content_summary)}</small></div><span class="hr14-badge">${esc(label(item.status))}</span><small>${esc(String(item.resolved_at || item.submitted_at || '').slice(0, 10))}</small></div>`).join('') : '<div class="hr14-empty">当前没有异议记录。</div>'}</div>`;

    const submit = (formId, build) => {
      const form = document.getElementById(formId);
      form?.addEventListener('submit', (event) => {
        event.preventDefault();
        const values = new FormData(form);
        const button = form.querySelector('button');
        run(button, form, () => build(values));
      });
    };
    submit('hr14-publicity-open', (values) => {
      if (!values.get('caseId') || !values.get('rankingId')) throw new Error('当前没有可发起公示的入选申报');
      return request(`/api/v1/hr/appointments/applications/${encodeURIComponent(values.get('caseId'))}/publicity/`, {
        rankingResultId: values.get('rankingId'), publicityNo: values.get('publicityNo'),
        startAt: new Date(values.get('startAt')).toISOString(), endAt: new Date(values.get('endAt')).toISOString(),
        noticeSnapshot: {source: 'HR14 拟聘公示工作区'},
      });
    });
    submit('hr14-objection-open', (values) => {
      if (!values.get('publicityId')) throw new Error('当前没有开放中的公示');
      return request(`/api/v1/hr/appointments/publicities/${encodeURIComponent(values.get('publicityId'))}/objections/`, {
        objectionNo: values.get('objectionNo'), contentSummary: values.get('summary'),
        submitterRef: values.get('submitter'), evidenceRefs: [],
      });
    });
    submit('hr14-objection-resolve', (values) => {
      if (!values.get('objectionId')) throw new Error('当前没有待处理异议');
      return request(`/api/v1/hr/appointments/publicity-objections/${encodeURIComponent(values.get('objectionId'))}/resolve/`, {
        outcome: values.get('outcome'), resolutionNote: values.get('note'),
      });
    });
    submit('hr14-publicity-close', (values) => {
      if (!values.get('publicityId')) throw new Error('当前没有开放中的公示');
      return request(`/api/v1/hr/appointments/publicities/${encodeURIComponent(values.get('publicityId'))}/close/`);
    });
  }

  function termLabel(id) {
    return (snapshot.recentTerms || []).find((item) => String(item.id) === String(id))?.term_no || '关联聘期';
  }

  function renderTermRows(rows, kind) {
    if (!rows.length) return '<div class="hr14-empty">当前没有相关记录。</div>';
    return rows.map((item) => {
      const isTerm = kind === 'term';
      const number = isTerm ? item.term_no : kind === 'renewal' ? item.renewal_no : item.change_no;
      const detail = isTerm
        ? `${item.level_code || '未分级'} · ${item.effective_from} 至 ${item.effective_to || '长期'}`
        : kind === 'renewal'
          ? `${termLabel(item.source_term_id)} · ${routeLabels[item.route] || item.route} · ${item.proposed_effective_from} 至 ${item.proposed_effective_to || '长期'}`
          : `${termLabel(item.source_term_id)} · ${changeLabels[item.change_type] || item.change_type} · 计划 ${item.effective_date}`;
      let actions = '';
      if (isTerm && item.status === 'ACTIVE') actions = `<button type="button" data-term-expiring="${esc(item.id)}">标记临期</button>`;
      if (!isTerm && kind === 'renewal' && item.status === 'READY') actions = `<button type="button" data-decision-kind="renewal" data-record="${esc(item.id)}" data-outcome="APPROVED">批准</button><button type="button" data-decision-kind="renewal" data-record="${esc(item.id)}" data-outcome="REJECTED">不续聘</button><button type="button" data-decision-kind="renewal" data-record="${esc(item.id)}" data-outcome="REAPPOINTMENT_REQUIRED">转重新竞聘</button>`;
      if (!isTerm && kind === 'change' && item.status === 'REVIEW_REQUIRED') actions = `<button type="button" data-decision-kind="change" data-record="${esc(item.id)}" data-outcome="APPROVED">批准</button><button type="button" data-decision-kind="change" data-record="${esc(item.id)}" data-outcome="REJECTED">驳回</button><button type="button" data-decision-kind="change" data-record="${esc(item.id)}" data-outcome="REAPPOINTMENT_REQUIRED">转重新竞聘</button>`;
      return `<div class="hr14-workflow-row"><div><b>${esc(number)}</b><small>${esc(detail)}</small></div><span class="hr14-badge">${esc(label(item.status))}</span>${actions && permissions.term ? `<div class="hr14-workflow-actions">${actions}</div><label class="hr14-decision-note"><span>决定依据</span><input data-note-for="${esc(item.id)}" placeholder="填写会议或审批依据"></label>` : '<small class="hr14-workflow-row__hint">当前状态没有可执行动作</small>'}</div>`;
    }).join('');
  }

  function renderTerm() {
    const target = host();
    if (!target) return;
    const terms = snapshot.recentTerms || [];
    const renewals = snapshot.recentRenewals || [];
    const changes = snapshot.recentTermChanges || [];
    const facts = snapshot.recentAppointments || [];
    const availableFacts = facts.filter((fact) => fact.status === 'EFFECTIVE' && !terms.some((term) => String(term.appointment_fact_id) === String(fact.id)));
    const correctableFacts = facts.filter((fact) => ['EFFECTIVE', 'REVISED'].includes(fact.status));
    const activeTerms = terms.filter((term) => ['ACTIVE', 'EXPIRING'].includes(term.status));
    const pendingRenewals = renewals.filter((item) => item.status === 'APPROVED');
    const pendingChanges = changes.filter((item) => item.status === 'APPROVED');
    const applied = [
      ...renewals.filter((item) => item.status === 'APPLIED').map((item) => ({number: item.renewal_no, kind: '续聘', source: termLabel(item.source_term_id)})),
      ...changes.filter((item) => item.status === 'APPLIED').map((item) => ({number: item.change_no, kind: changeLabels[item.change_type] || item.change_type, source: termLabel(item.source_term_id)})),
    ];

    target.innerHTML = `
      <div class="hr14-workflow__head"><div><h2>聘期治理与正式生效</h2><p>续聘和变更批准只形成治理决定；只有正式生效成功后，才形成后继聘任与聘期事实。</p></div></div>
      ${permissions.term ? `<div class="hr14-workflow-grid">
        <form id="hr14-term-register" class="hr14-workflow-form compact">
          <h3>从正式聘任建立聘期</h3>
          <label class="wide"><span>尚未建期的正式聘任</span><select name="factId" required>${availableFacts.length ? availableFacts.map((item) => `<option value="${esc(item.id)}">${esc(item.appointment_no)} · ${esc(item.level_code || '未分级')}</option>`).join('') : '<option value="">暂无可建立聘期的记录</option>'}</select></label>
          <label><span>聘期编号</span><input name="termNo" required></label>
          <label><span>结束日期</span><input name="effectiveTo" type="date"></label>
          <label><span>续聘提醒</span><input name="renewalDueAt" type="date"></label>
          <button type="submit">建立聘期</button>
        </form>
        <form id="hr14-renewal-open" class="hr14-workflow-form compact">
          <h3>发起续聘</h3>
          <label class="wide"><span>当前聘期</span><select name="termId" required>${activeTerms.length ? activeTerms.map((item) => `<option value="${esc(item.id)}">${esc(item.term_no)} · ${esc(item.effective_to || '长期')}</option>`).join('') : '<option value="">暂无可续聘的聘期</option>'}</select></label>
          <label><span>续聘案件号</span><input name="renewalNo" required></label>
          <label><span>续聘路径</span><select name="route"><option value="DIRECT_RENEWAL">直接续聘</option><option value="TERM_ASSESSMENT">聘期考核后续聘</option><option value="REAPPOINTMENT">重新竞聘</option></select></label>
          <label><span>开始日期</span><input name="from" type="date" required></label>
          <label><span>结束日期</span><input name="to" type="date"></label>
          <label><span>续聘等级</span><input name="level" placeholder="可选"></label>
          <label class="wide"><span>聘期考核结果引用</span><input name="assessment" placeholder="选择考核路径时按制度填写"></label>
          <button type="submit">创建续聘案件</button>
        </form>
        <form id="hr14-change-open" class="hr14-workflow-form compact">
          <h3>发起聘期变更</h3>
          <label class="wide"><span>当前聘期</span><select name="termId" required>${activeTerms.length ? activeTerms.map((item) => `<option value="${esc(item.id)}">${esc(item.term_no)} · ${esc(item.level_code || '未分级')}</option>`).join('') : '<option value="">暂无可变更的聘期</option>'}</select></label>
          <label><span>变更案件号</span><input name="changeNo" required></label>
          <label><span>变更类型</span><select name="type"><option value="PROMOTION">高聘 / 晋升</option><option value="DOWNGRADE">低聘</option><option value="TERMINATION">解聘 / 终止</option><option value="TRANSFER">转岗</option><option value="CORRECTION" disabled>正式纠错（使用下方专门入口）</option></select></label>
          <label><span>计划生效日期</span><input name="date" type="date" required></label>
          <label><span>目标等级</span><input name="level" placeholder="高聘或低聘时填写"></label>
          <label class="wide"><span>目标岗位（转岗时必选）</span><select name="targetPosition"><option value="">非转岗无需选择</option>${(setupSnapshot.positions || []).map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('')}</select></label>
          <label class="wide"><span>变更依据</span><textarea name="reason" required></textarea></label>
          <div class="hr14-workflow__notice wide">转岗目标来自 HR02 在用且有余量的岗位，批准后执行生效时自动建立并核验岗位容量预占；正式纠错使用专门授权入口。</div>
          <button type="submit">创建变更案件</button>
        </form>
      </div>` : permissionNotice('当前账号没有聘期治理权限。')}
      ${permissions.factCorrect ? `<form id="hr14-fact-correct" class="hr14-workflow-form compact hr14-authority-form">
        <h3>正式聘任事实纠错</h3>
        <label class="wide"><span>待纠错正式聘任</span><select name="factId" required><option value="">请选择</option>${correctableFacts.map((item) => `<option value="${esc(item.id)}">${esc(item.appointment_no)} · ${esc(item.level_code || '未分级')}</option>`).join('')}</select></label>
        <label><span>后继聘任编号</span><input name="appointmentNo" required></label>
        <label><span>更正后岗位（可选）</span><select name="positionId"><option value="">保持原岗位</option>${(setupSnapshot.positions || []).map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('')}</select></label>
        <label><span>更正后等级（可选）</span><input name="levelCode"></label>
        <label><span>更正后开始日（可选）</span><input name="effectiveFrom" type="date"></label>
        <label><span>更正后结束日（可选）</span><input name="effectiveTo" type="date"></label>
        <label><span>授权决定编号</span><input name="authorityRef" required></label>
        <label><span>防重复办理号</span><input name="idempotencyKey" required></label>
        <label class="wide"><span>纠错原因</span><textarea name="reason" required></textarea></label>
        <label class="wide"><span>依据材料引用</span><input name="documentRef" required placeholder="HR03 受控文件编号或档案引用"></label>
        <button type="submit">追加纠错后继事实</button>
      </form>` : ''}
      <div class="hr14-term-ledgers">
        <section><h3>聘期台账</h3><div class="hr14-workflow-list">${renderTermRows(terms, 'term')}</div></section>
        <section><h3>续聘案件</h3><div class="hr14-workflow-list">${renderTermRows(renewals, 'renewal')}</div></section>
        <section><h3>变更案件</h3><div class="hr14-workflow-list">${renderTermRows(changes, 'change')}</div></section>
      </div>
      <div class="hr14-effect-boundary">
        <div class="hr14-workflow__head"><div><h3>正式生效工作区</h3><p>跨域任职变更必须取得真实回执。半失败保持“生效待重试”，不会显示成功。</p></div></div>
        ${permissions.term ? renderEffects(pendingRenewals, pendingChanges) : permissionNotice('当前账号没有正式生效权限。')}
        ${applied.length ? `<h3 class="hr14-workflow-subtitle">近期已正式生效</h3><div class="hr14-workflow-list">${applied.map((item) => `<div class="hr14-workflow-row"><div><b>${esc(item.number)}</b><small>${esc(item.source)} · ${esc(item.kind)}</small></div><span class="hr14-badge">已正式生效</span></div>`).join('')}</div>` : ''}
      </div>`;

    bindTermForms();
  }

  function renderEffects(renewals, changes) {
    const rows = [
      ...renewals.map((item) => ({kind: 'renewal', id: item.id, number: item.renewal_no, source: termLabel(item.source_term_id), detail: `${item.proposed_effective_from} 至 ${item.proposed_effective_to || '长期'}`})),
      ...changes.map((item) => ({kind: 'change', id: item.id, number: item.change_no, source: termLabel(item.source_term_id), detail: changeLabels[item.change_type] || item.change_type, changeType: item.change_type})),
    ];
    if (!rows.length) return '<div class="hr14-empty">当前没有已批准、待正式生效的续聘或变更。</div>';
    return `<div class="hr14-workflow-list">${rows.map((item) => {
      if (item.changeType === 'CORRECTION') {
        const reason = '正式纠错必须使用专门纠错授权入口';
        return `<div class="hr14-workflow-row"><div><b>${esc(item.number)}</b><small>${esc(item.source)} · ${esc(reason)}</small></div><span class="hr14-badge">暂不可生效</span></div>`;
      }
      const termination = item.changeType === 'TERMINATION';
      return `<div class="hr14-workflow-row hr14-effect-row"><div><b>${esc(item.number)}</b><small>${esc(item.source)} · ${esc(item.detail)}</small></div><span class="hr14-badge">已批准，待生效</span><form class="hr14-effect-form" data-effect-kind="${item.kind}" data-change-type="${esc(item.changeType || '')}" data-record="${esc(item.id)}"><label><span>后继聘任编号</span><input name="appointmentNo" required></label>${termination ? '' : '<label><span>后继聘期编号</span><input name="termNo" required></label>'}${termination ? '' : '<label><span>下次续聘提醒</span><input name="renewalDueAt" type="date"></label>'}<button type="submit">${item.changeType === 'TRANSFER' ? '预占岗位并正式生效' : '执行正式生效'}</button></form></div>`;
    }).join('')}</div>`;
  }

  function bindTermForms() {
    const bind = (id, build) => {
      const form = document.getElementById(id);
      form?.addEventListener('submit', (event) => {
        event.preventDefault();
        const values = new FormData(form);
        run(form.querySelector('button'), form, () => build(values));
      });
    };
    bind('hr14-term-register', (values) => {
      if (!values.get('factId')) throw new Error('当前没有可建立聘期的正式聘任');
      return request(`/api/v1/hr/appointments/appointment-facts/${encodeURIComponent(values.get('factId'))}/term/`, {termNo: values.get('termNo'), effectiveTo: values.get('effectiveTo') || null, renewalDueAt: values.get('renewalDueAt') || null});
    });
    bind('hr14-renewal-open', (values) => {
      if (!values.get('termId')) throw new Error('当前没有可续聘的聘期');
      return request(`/api/v1/hr/appointments/terms/${encodeURIComponent(values.get('termId'))}/renewals/`, {renewalNo: values.get('renewalNo'), route: values.get('route'), proposedEffectiveFrom: values.get('from'), proposedEffectiveTo: values.get('to') || null, proposedLevelCode: values.get('level'), hr12TermResultRef: values.get('assessment')});
    });
    bind('hr14-change-open', (values) => {
      if (!values.get('termId')) throw new Error('当前没有可变更的聘期');
      if (values.get('type') === 'TRANSFER' && !values.get('targetPosition')) throw new Error('转岗必须选择 HR02 目标岗位');
      return request(`/api/v1/hr/appointments/terms/${encodeURIComponent(values.get('termId'))}/changes/`, {changeNo: values.get('changeNo'), changeType: values.get('type'), effectiveDate: values.get('date'), targetPositionInstanceId: values.get('type') === 'TRANSFER' ? Number(values.get('targetPosition')) : null, targetLevelCode: values.get('level'), reason: values.get('reason')});
    });
    bind('hr14-fact-correct', (values) => {
      if (!values.get('factId')) throw new Error('请选择待纠错的正式聘任事实');
      const payload = {
        appointmentNo: values.get('appointmentNo'),
        reason: values.get('reason'),
        authorityRef: values.get('authorityRef'),
        evidence: {documentRef: values.get('documentRef')},
      };
      if (values.get('positionId')) payload.positionInstanceId = Number(values.get('positionId'));
      if (values.get('levelCode')) payload.levelCode = values.get('levelCode');
      if (values.get('effectiveFrom')) payload.effectiveFrom = values.get('effectiveFrom');
      if (values.get('effectiveTo')) payload.effectiveTo = values.get('effectiveTo');
      return request(`/api/v1/hr/appointments/appointment-facts/${encodeURIComponent(values.get('factId'))}/corrections/`, payload, 'POST', {'Idempotency-Key': values.get('idempotencyKey')});
    });

    document.querySelectorAll('[data-term-expiring]').forEach((button) => button.addEventListener('click', () => run(button, button.closest('.hr14-workflow-row'), () => request(`/api/v1/hr/appointments/terms/${encodeURIComponent(button.dataset.termExpiring)}/expiring/`))));
    document.querySelectorAll('[data-decision-kind]').forEach((button) => button.addEventListener('click', () => {
      const scope = button.closest('.hr14-workflow-row');
      const note = scope.querySelector(`[data-note-for="${CSS.escape(button.dataset.record)}"]`)?.value.trim() || '';
      if (!note) return setMessage(scope, '请先填写决定依据', true);
      const base = button.dataset.decisionKind === 'renewal' ? 'renewals' : 'term-changes';
      run(button, scope, () => request(`/api/v1/hr/appointments/${base}/${encodeURIComponent(button.dataset.record)}/decision/`, {outcome: button.dataset.outcome, decisionSnapshot: {note}}));
    }));
    document.querySelectorAll('.hr14-effect-form').forEach((form) => form.addEventListener('submit', (event) => {
      event.preventDefault();
      const values = new FormData(form);
      const base = form.dataset.effectKind === 'renewal' ? 'renewals' : 'term-changes';
      run(form.querySelector('button'), form.closest('.hr14-effect-row'), async () => {
        let reservationId = null;
        if (form.dataset.changeType === 'TRANSFER') {
          const held = await request(`/api/v1/hr/appointments/term-changes/${encodeURIComponent(form.dataset.record)}/capacity-reservation/`);
          reservationId = held.data && held.data.reservationId;
          if (!reservationId) throw new Error('HR02 岗位预占未返回有效凭证');
        }
        return request(`/api/v1/hr/appointments/${base}/${encodeURIComponent(form.dataset.record)}/apply-effect/`, {appointmentNo: values.get('appointmentNo'), successorTermNo: values.get('termNo') || '', renewalDueAt: values.get('renewalDueAt') || null, reservationId});
      });
    }));
  }

  function renderSection() {
    if (!snapshot) return;
    if (['policies', 'quota', 'competitions'].includes(section)) return renderCompetition();
    if (section === 'applications') return renderApplications();
    if (section === 'ranking') return renderRanking();
    if (section === 'publicity') return renderPublicity();
    if (section === 'term_changes') return renderTerm();
  }

  if (['policies', 'quota', 'competitions', 'applications', 'ranking', 'publicity', 'term_changes'].includes(section)) {
    const target = host();
    if (target) target.innerHTML = '<div class="hr14-empty">正在读取真实办理数据…</div>';
    reload().catch((error) => {
      if (target) target.innerHTML = `<div class="hr14-empty">办理数据读取失败：${esc(error.message)}。未知状态不会按正常处理。</div>`;
    });
  }
})();
