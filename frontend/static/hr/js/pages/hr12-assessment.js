/* HR12 assessment workspace — real data boot for the shared HR V2 shell. */
(() => {
  const root = document.querySelector("[data-module='HR12']");
  if (!root || root.dataset.hr12Booted === 'true') return;
  root.dataset.hr12Booted = 'true';

  const section = root.dataset.section || 'overview';
  const REQUEST_TIMEOUT_MS = 6000;
  const zhStatus = {
    PUBLISHED: '已发布', DRAFT: '草稿', ACTIVE: '有效', INACTIVE: '停用',
    PROPOSED: '待审定', PUBLICITY: '公示中', FINALIZED: '已定稿', READY: '证据已锁定',
    OK: '已接通', UNAVAILABLE: '暂不可用', PARTIAL: '部分可用',
    OPEN: '进行中', COMPLETED: '已完成', CLOSED: '已关闭', PENDING: '待处理',
    PASS: '通过', FAIL: '不通过', BLOCKED: '已阻断', NOT_EVALUATED: '待评价',
    ARCHIVED: '已归档', FAILED: '失败',
  };
  const sourceNames = {
    hr03: '教职工主档', hr07: '合同聘用', hr09: '资格资质', hr10: '教师发展',
    hr11: '考勤时间', academic: '教务数据', research: '科研数据', ethicsFact: '师德事实',
  };
  const esc = (value) => String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[char],
  );

  function cookie(name) {
    const match = document.cookie.split(';').map((value) => value.trim())
      .find((value) => value.startsWith(`${name}=`));
    return match ? decodeURIComponent(match.slice(name.length + 1)) : '';
  }

  async function requestJson(url, options = {}) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        ...options,
        credentials: 'same-origin',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          ...(options.method && options.method !== 'GET'
            ? {
                'X-CSRFToken': cookie('csrftoken'),
                ...(options.body instanceof FormData ? {} : {'Content-Type': 'application/json'}),
              }
            : {}),
          ...(options.headers || {}),
        },
        signal: controller.signal,
      });
      let body = {};
      try { body = await response.json(); } catch (_error) { body = {}; }
      if (!response.ok) {
        const blockers = body?.error?.details?.blockers;
        const blockerText = Array.isArray(blockers)
          ? blockers.map((item) => item.code || '').filter(Boolean).join('、')
          : '';
        throw new Error(body?.message || body?.error?.message || blockerText || `请求失败 ${response.status}`);
      }
      return body.data ?? body;
    } finally {
      window.clearTimeout(timer);
    }
  }

  const getJson = (url) => requestJson(url);
  const postJson = (url, payload = {}) => requestJson(url, {method: 'POST', body: JSON.stringify(payload)});
  const postForm = (url, payload) => requestJson(url, {method: 'POST', body: payload});

  async function auditedDownload(url, fallbackName) {
    const reason = window.prompt('请输入本次查阅事由（将写入审计记录）：', '考核审定复核');
    if (reason === null) return false;
    if (!reason.trim()) throw new Error('下载考核纪要必须填写查阅事由。');
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {'X-HR-Access-Reason': reason.trim(), 'X-Requested-With': 'XMLHttpRequest'}
    });
    if (!response.ok) {
      let body = {};
      try { body = await response.json(); } catch (_error) { /* handled below */ }
      throw new Error(body?.error?.message || '考核纪要下载失败');
    }
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = blobUrl; link.download = fallbackName; link.click();
    URL.revokeObjectURL(blobUrl);
    return true;
  }

  function empty(title, message) {
    return `<div class="hr12-empty"><strong>${esc(title)}</strong>${esc(message)}</div>`;
  }

  function statusClass(status) {
    if (['ACTIVE', 'PUBLISHED', 'OK', 'READY', 'FINALIZED', 'COMPLETED', 'PASS', 'ARCHIVED'].includes(status)) return 'hr12-pill--success';
    if (['DRAFT', 'INACTIVE', 'PARTIAL', 'UNAVAILABLE', 'PROPOSED', 'PUBLICITY', 'PENDING', 'NOT_EVALUATED'].includes(status)) return 'hr12-pill--warning';
    return 'hr12-pill--info';
  }

  function row(name, sub, middle, status) {
    const shown = zhStatus[status] || status || '—';
    return `<div class="hr12-row"><div><strong>${esc(name || '未命名')}</strong><small>${esc(sub || '')}</small></div><div class="hr12-row__meta">${esc(middle || '—')}</div><span class="hr12-pill ${statusClass(status)}">${esc(shown)}</span></div>`;
  }

  function annualRow(item) {
    const result = item.formalResult;
    const grade = result?.displayGrade?.['zh-CN'] || result?.gradeCode || '';
    const label = item.staffName || '人员档案暂不可用';
    const year = item.businessYear || item.academicYear || item.cycleName || '年度考核';
    if (result) {
      return `<div class="hr12-row" data-annual-case="${esc(item.id)}" data-case-status="FINALIZED">
        <div><strong>${esc(label)}</strong><small>${esc(year)} · 正式结果版本 ${esc(result.resultVersionNo || 1)}</small></div>
        <div class="hr12-row__meta">${esc(grade || '已定稿')}</div>
        <span class="hr12-pill hr12-pill--success">已定稿</span>
      </div>`;
    }
    let action = '<span class="hr12-pill hr12-pill--warning">待处理</span>';
    if (!item.providerSnapshotReady) {
      action = '<button type="button" class="hr-v2-button hr-v2-button--primary" data-annual-snapshot>锁定证据快照</button>';
    } else if (!item.decisionSessionId) {
      action = '<span class="hr12-pill hr12-pill--warning">待完成审定会</span>';
    } else if (item.status === 'PROPOSED' || item.status === 'PUBLICITY') {
      action = '<div class="hr12-annual-action"><span class="hr12-status-note">档次由已提交评分和已发布规则自动计算</span><button type="button" class="hr-v2-button hr-v2-button--primary" data-annual-finalize>正式审定</button></div>';
    }
    return `<div class="hr12-row" data-annual-case="${esc(item.id)}" data-decision-session="${esc(item.decisionSessionId || '')}" data-case-status="${esc(item.status || '')}">
      <div><strong>${esc(label)}</strong><small>${esc(year)} · ${esc(item.cycleName || '')}</small></div>
      <div class="hr12-row__meta">${esc(item.providerSnapshotReady ? '证据已锁定' : '待锁定证据')} · ${esc(zhStatus[item.status] || item.status || '—')}</div>${action}</div>`;
  }

  async function loadAnnualCases() {
    const box = document.getElementById('workRows');
    if (!box) return;
    try {
      const value = await getJson('/api/v1/hr/assessments/annual');
      const items = Array.isArray(value) ? value : [];
      box.innerHTML = items.length ? items.map(annualRow).join('') : empty('暂无年度考核对象', '当前学校尚未建立可办理的年度考核对象。');
    } catch (error) {
      box.innerHTML = empty('年度考核数据读取失败', error.message || '请稍后重试。');
    }
  }

  function optionHtml(items) {
    return (items || []).map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('');
  }

  async function mountAnnualSetup() {
    if (section !== 'annual' || root.querySelector('[data-annual-setup]')) return;
    const host = document.createElement('section');
    host.className = 'hr12-action-card';
    host.dataset.annualSetup = 'true';
    host.innerHTML = `<h2>年度考核启动</h2><p>先用已发布制度建立周期，再把当前学校人员纳入考核。周期发布时会冻结制度与时间边界。</p>
      <div class="hr12-action-result" data-setup-result role="status" aria-live="polite"></div>
      <div class="hr12-action-grid">
        <form class="hr12-action-form open" data-cycle-form>
          <h3>1 · 新建并发布周期</h3>
          <div class="hr12-action-field"><label>周期编号<input name="cycleNo" required placeholder="ANNUAL_2026"></label></div>
          <div class="hr12-action-field"><label>周期名称<input name="name" required placeholder="2026 年度考核"></label></div>
          <div class="hr12-action-field"><label>业务年度<input name="businessYear" type="number" min="2000" max="2100" required></label></div>
          <div class="hr12-action-field"><label>已发布制度<select name="policyVersionId" required><option value="">请选择</option></select></label></div>
          <div class="hr12-action-field"><label>开始时间<input name="startAt" type="datetime-local" required></label></div>
          <div class="hr12-action-field"><label>结束时间<input name="endAt" type="datetime-local" required></label></div>
          <div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="submit">建立周期</button></div>
        </form>
        <form class="hr12-action-form open" data-case-form>
          <h3>2 · 纳入考核对象</h3>
          <div class="hr12-action-field"><label>考核周期<select name="cycleId" required><option value="">请选择</option></select></label></div>
          <div class="hr12-action-field"><label>教职工<select name="staffId" required><option value="">请选择</option></select></label></div>
          <div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="submit">创建年度考核对象</button></div>
        </form>
      </div>`;
    root.querySelector('.hr12-principle')?.before(host);
    const status = host.querySelector('[data-setup-result]');
    const show = (message, error = false) => {
      status.className = `hr12-action-result show ${error ? 'error' : 'ok'}`;
      status.textContent = message;
    };
    async function refreshOptions() {
      const data = await getJson('/api/v1/hr/assessments/setup-options');
      host.querySelector('[name="policyVersionId"]').innerHTML = `<option value="">请选择</option>${optionHtml(data.policies)}`;
      host.querySelector('[name="cycleId"]').innerHTML = `<option value="">请选择</option>${optionHtml(data.cycles)}`;
      host.querySelector('[name="staffId"]').innerHTML = `<option value="">请选择</option>${optionHtml(data.staff)}`;
    }
    host.querySelector('[data-cycle-form]').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('button');
      button.disabled = true;
      try {
        await postJson('/api/v1/hr/assessments/cycles', Object.fromEntries(new FormData(form).entries()));
        show('考核周期已建立并发布，制度与时间边界已冻结。');
        form.reset();
        await refreshOptions();
      } catch (error) { show(error.message || '周期建立失败', true); }
      finally { button.disabled = false; }
    });
    host.querySelector('[data-case-form]').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('button');
      button.disabled = true;
      try {
        await postJson('/api/v1/hr/assessments/annual/cases', Object.fromEntries(new FormData(form).entries()));
        show('年度考核对象已建立，可在上方锁定证据快照。');
        await loadAnnualCases();
      } catch (error) { show(error.message || '考核对象建立失败', true); }
      finally { button.disabled = false; }
    });
    try { await refreshOptions(); }
    catch (error) { show(error.message || '启动选项读取失败', true); }
  }

  function showAnnualActionError(message) {
    const box = document.getElementById('workRows');
    if (!box) return;
    let notice = document.getElementById('annualActionStatus');
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'annualActionStatus';
      notice.className = 'hr12-status-note hr12-status-note--error';
      notice.setAttribute('role', 'status');
      notice.setAttribute('aria-live', 'polite');
      box.before(notice);
    }
    notice.textContent = message || '办理失败，请稍后重试。';
  }

  async function handleAnnualAction(event) {
    const button = event.target.closest('[data-annual-snapshot], [data-annual-finalize]');
    if (!button) return;
    const caseRow = button.closest('[data-annual-case]');
    if (!caseRow) return;
    const caseId = caseRow.dataset.annualCase;
    button.disabled = true;
    try {
      if (button.matches('[data-annual-snapshot]')) {
        await postJson(`/api/v1/hr/assessments/cases/${caseId}/provider-snapshot`, {});
      } else {
        const decisionSessionId = caseRow.dataset.decisionSession || '';
        await postJson(`/api/v1/hr/assessments/cases/${caseId}/finalize`, {
          decisionSessionId, decisionReason: '年度考核工作台正式审定',
        });
      }
      await loadAnnualCases();
    } catch (error) {
      showAnnualActionError(error.message || '办理失败');
    } finally {
      button.disabled = false;
    }
  }

  async function loadAuthorityWorkbench() {
    const box = document.getElementById('workRows');
    if (!box) return;
    try {
      const payload = await getJson(`/api/v1/hr/assessments/workbench/${section}`);
      const items = Array.isArray(payload?.rows) ? payload.rows : [];
      box.innerHTML = items.length
        ? items.map((item) => row(item.name, item.sub, item.meta, item.status)).join('')
        : empty('当前没有可展示的业务事实', '当前学校在此工作区尚未形成记录；页面不会用演示数据替代。');
    } catch (error) {
      box.innerHTML = empty('工作区数据读取失败', error.message || '请检查权限或稍后重试。');
    }
  }

  function reviewMessage(host, message, error = false) {
    const status = host.querySelector('[data-review-result]');
    if (!status) return;
    status.className = `hr12-action-result show ${error ? 'error' : 'ok'}`;
    status.textContent = message;
  }

  function multiSelectOptions(items) {
    return (items || []).map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join('');
  }

  function reviewerTaskHtml(item) {
    const done = Boolean(item.evaluation);
    const score = item.evaluation?.rating?.overallScore || '';
    return `<article class="hr12-action-form open" data-review-task="${esc(item.id)}">
      <h3>${esc(item.staffName)} · ${esc(item.cycleName || '考核评议')}</h3>
      <p>${esc(item.reviewerRole)} · ${done ? `已提交 ${score} 分` : '待本人提交评分与评语'}</p>
      ${done ? `<div class="hr12-action-note">评分：${esc(score)} 分<br>评语：${esc(item.evaluation.comment || '—')}</div>` : `
        <form data-evaluation-form>
          <div class="hr12-action-field"><label>综合评分（0—100）<input name="overallScore" type="number" min="0" max="100" step="0.01" required></label></div>
          <div class="hr12-action-field"><label>评议意见<textarea name="comment" rows="3" maxlength="2000" required placeholder="请依据工作实绩、师德表现和岗位职责填写具体意见"></textarea></label></div>
          <div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="submit">确认提交评议</button></div>
        </form>`}
    </article>`;
  }

  async function mountReviewWorkbench() {
    if (section !== 'review' || root.querySelector('[data-review-workbench]')) return;
    const host = document.createElement('section');
    host.className = 'hr12-action-card';
    host.dataset.reviewWorkbench = 'true';
    host.innerHTML = `<h2>评议与集体审定办理</h2>
      <p>按“分配评议人—本人提交评议—集体会议审定—上传并封存会议纪要”的顺序办理。</p>
      <div class="hr12-action-result" data-review-result role="status" aria-live="polite"></div>
      <div class="hr12-action-grid" data-review-tools></div>`;
    root.querySelector('.hr12-principle')?.before(host);
    const tools = host.querySelector('[data-review-tools]');
    const [adminResult, mineResult, decisionResult] = await Promise.allSettled([
      getJson('/api/v1/hr/assessments/review-administration-options'),
      getJson('/api/v1/hr/assessments/reviewer-assignments/mine'),
      getJson('/api/v1/hr/assessments/decision-options'),
    ]);

    if (adminResult.status === 'fulfilled') {
      const data = adminResult.value || {};
      const panel = document.createElement('form');
      panel.className = 'hr12-action-form open';
      panel.dataset.reviewerAssignForm = 'true';
      panel.innerHTML = `<h3>1 · 分配评议任务</h3>
        <div class="hr12-action-field"><label>考核对象<select name="caseId" required><option value="">请选择</option>${optionHtml(data.cases)}</select></label></div>
        <div class="hr12-action-field"><label>评议人<select name="reviewerStaffId" required><option value="">请选择</option>${optionHtml(data.staff)}</select></label></div>
        <div class="hr12-action-field"><label>评议环节<select name="reviewerRole" required><option value="">请选择</option>${optionHtml(data.reviewerRoles)}</select></label></div>
        <div class="hr12-action-field"><label>完成时限<input name="dueAt" type="datetime-local"></label></div>
        <div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="submit">分配任务</button></div>`;
      panel.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = Object.fromEntries(new FormData(panel).entries());
        const caseId = body.caseId;
        delete body.caseId;
        const button = panel.querySelector('button');
        button.disabled = true;
        try {
          await postJson(`/api/v1/hr/assessments/cases/${caseId}/reviewers`, body);
          reviewMessage(host, '评议任务已分配；被分配人员可在“我的待评任务”中办理。');
          panel.reset();
        } catch (error) { reviewMessage(host, error.message || '评议任务分配失败', true); }
        finally { button.disabled = false; }
      });
      tools.append(panel);
    }

    if (mineResult.status === 'fulfilled') {
      const tasks = Array.isArray(mineResult.value) ? mineResult.value : [];
      const panel = document.createElement('section');
      panel.className = 'hr12-action-form open';
      panel.innerHTML = `<h3>2 · 我的待评任务</h3><div data-my-review-tasks>${tasks.length
        ? tasks.map(reviewerTaskHtml).join('')
        : '<div class="hr12-action-note">当前账号暂无评议任务。</div>'}</div>`;
      panel.addEventListener('submit', async (event) => {
        const form = event.target.closest('[data-evaluation-form]');
        if (!form) return;
        event.preventDefault();
        const task = form.closest('[data-review-task]');
        const body = Object.fromEntries(new FormData(form).entries());
        body.indicatorEvaluations = [];
        const button = form.querySelector('button');
        button.disabled = true;
        try {
          await postJson(`/api/v1/hr/assessments/reviewer-assignments/${task.dataset.reviewTask}/evaluations`, body);
          reviewMessage(host, '评议已提交并封存，不能无痕修改。');
          task.outerHTML = reviewerTaskHtml({
            id: task.dataset.reviewTask,
            staffName: task.querySelector('h3')?.textContent || '考核对象',
            reviewerRole: '本人评议',
            evaluation: {rating: {overallScore: body.overallScore}, comment: body.comment},
          });
        } catch (error) { reviewMessage(host, error.message || '评议提交失败', true); }
        finally { button.disabled = false; }
      });
      tools.append(panel);
    }

    if (decisionResult.status === 'fulfilled') {
      const data = decisionResult.value || {};
      const panel = document.createElement('section');
      panel.className = 'hr12-action-form open';
      panel.innerHTML = `<h3>3 · 集体审定会议</h3>
        <form data-decision-create-form>
          <div class="hr12-action-field"><label>考核周期<select name="cycleId" required><option value="">请选择</option>${optionHtml(data.cycles)}</select></label></div>
          <div class="hr12-action-field"><label>审定对象（可多选）<select name="caseIds" multiple size="6" required>${multiSelectOptions(data.cases)}</select></label></div>
          <div class="hr12-action-field"><label>参会人员（至少两人，可多选）<select name="participantStaffIds" multiple size="6" required>${multiSelectOptions(data.staff)}</select></label></div>
          <div class="hr12-action-field"><label>法定到会人数<input name="requiredCount" type="number" min="2" required value="2"></label></div>
          <div class="hr12-action-field"><label>会议时间<input name="meetingAt" type="datetime-local" required></label></div>
          <div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="submit">建立审定会议</button></div>
        </form>
        <form data-decision-complete-form hidden>
          <div class="hr12-action-note">会议建立后，请上传签字或盖章的正式纪要。文件会进入当前学校受控存储并计算校验哈希。</div>
          <div class="hr12-action-field"><label>会议纪要（PDF/Word，20 MiB 以内）<input name="file" type="file" accept=".pdf,.doc,.docx" required></label></div>
          <div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="submit">上传纪要并完成审定会</button></div>
        </form>`;
      const createForm = panel.querySelector('[data-decision-create-form]');
      const completeForm = panel.querySelector('[data-decision-complete-form]');
      const cycleSelect = createForm.querySelector('[name="cycleId"]');
      const caseSelect = createForm.querySelector('[name="caseIds"]');
      const allCases = Array.isArray(data.cases) ? data.cases : [];
      cycleSelect.addEventListener('change', () => {
        caseSelect.innerHTML = multiSelectOptions(allCases.filter((item) => item.cycleId === cycleSelect.value));
      });
      createForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const values = new FormData(createForm);
        const body = {
          cycleId: values.get('cycleId'),
          caseIds: values.getAll('caseIds'),
          participantStaffIds: values.getAll('participantStaffIds'),
          requiredCount: values.get('requiredCount'),
          meetingAt: values.get('meetingAt'),
        };
        const button = createForm.querySelector('button');
        button.disabled = true;
        try {
          const value = await postJson(`/api/v1/hr/assessments/cycles/${body.cycleId}/decision-sessions`, body);
          const session = value.decisionSession || value;
          completeForm.dataset.sessionId = session.id;
          completeForm.hidden = false;
          createForm.hidden = true;
          reviewMessage(host, '审定会议已建立。请上传正式会议纪要后完成审定。');
        } catch (error) { reviewMessage(host, error.message || '审定会议建立失败', true); }
        finally { button.disabled = false; }
      });
      completeForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = completeForm.querySelector('button');
        const sessionId = completeForm.dataset.sessionId;
        button.disabled = true;
        try {
          const uploaded = await postForm(
            `/api/v1/hr/assessments/decision-sessions/${sessionId}/minutes`,
            new FormData(completeForm),
          );
          const document = uploaded.document || uploaded;
          await postJson(`/api/v1/hr/assessments/decision-sessions/${sessionId}/complete`, {
            minutesDocumentRef: document.id,
          });
          reviewMessage(host, '审定会议已完成，会议纪要已封存，可回到年度考核办理正式定稿。');
          completeForm.innerHTML = '<div class="hr12-action-note">本次审定会已完成，会议纪要已封存。</div><div class="hr12-action-toolbar"><button class="hr12-action-btn" type="button" data-download-minutes>审计下载会议纪要</button></div>';
          completeForm.querySelector('[data-download-minutes]').addEventListener('click', async (downloadEvent) => {
            const downloadButton = downloadEvent.currentTarget;
            downloadButton.disabled = true;
            try {
              await auditedDownload(
                `/api/v1/hr/assessments/decision-sessions/${sessionId}/minutes/${document.id}`,
                document.filename || '考核审定会议纪要',
              );
              reviewMessage(host, '会议纪要已下载，本次查阅已记录审计。');
            } catch (error) { reviewMessage(host, error.message || '会议纪要下载失败', true); }
            finally { downloadButton.disabled = false; }
          });
          loadAuthorityWorkbench();
        } catch (error) { reviewMessage(host, error.message || '会议纪要上传或审定完成失败', true); }
        finally { button.disabled = false; }
      });
      tools.append(panel);
    }

    if (!tools.children.length) {
      tools.innerHTML = '<div class="hr12-action-note">当前账号暂无评议或审定办理权限。如职责已调整，请联系学校权限管理员同步岗位账号关系。</div>';
    }
  }

  function lifecycleItemHtml(item) {
    const result = item.result || {};
    const actions = item.actions || {};
    const grade = result.displayGrade?.['zh-CN'] || result.gradeCode || '正式结果';
    const notice = item.notice;
    const acknowledgement = item.acknowledgement;
    const objection = item.objection;
    const archive = item.archive;
    return `<article class="hr12-action-form open" data-lifecycle-result="${esc(result.id)}" data-result-version="${esc(result.resultVersionNo || 1)}">
      <h3>${esc(item.staffName)} · ${esc(grade)}</h3>
      <p>${esc(item.cycleName || '考核结果')} · 结果版本 ${esc(result.resultVersionNo || 1)}</p>
      <div class="hr12-action-note">
        告知：${esc(notice ? (zhStatus[notice.deliveryStatus] || notice.deliveryStatus) : '待生成')}　
        本人确认：${esc(acknowledgement ? acknowledgement.acknowledgementStatus : '待确认')}　
        异议：${esc(objection ? (objection.decisionCode || zhStatus[objection.status] || objection.status) : '无')}　
        归档：${esc(archive ? '已归档' : '待归档')}
      </div>
      ${actions.canIssueNotice ? '<div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="button" data-issue-notice>生成结果告知单</button></div>' : ''}
      ${actions.canConfirmDelivery ? `<div class="hr12-action-field"><label>送达回执编号<input data-delivery-receipt maxlength="200" placeholder="系统消息回执、邮件回执或纸质签收编号"></label></div><div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="button" data-confirm-delivery data-notice-id="${esc(notice.id)}">确认已送达</button></div>` : ''}
      ${actions.canAcknowledge ? `<div class="hr12-action-field"><label>本人意见<select data-ack-status><option value="RECEIVED_AGREE">已收到并同意</option><option value="RECEIVED_RESERVATION">已收到，保留意见</option><option value="RECEIVED_DISAGREE">已收到，不同意</option></select></label></div><div class="hr12-action-field"><label>本人意见说明<textarea data-ack-opinion rows="3" maxlength="2000" placeholder="保留意见或不同意时必须填写"></textarea></label></div><div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="button" data-acknowledge>确认本人意见</button></div>` : ''}
      ${actions.canSubmitObjection ? `<div class="hr12-action-field"><label>结果异议理由<textarea data-objection-reason rows="4" minlength="10" maxlength="4000" placeholder="请写明异议事实、依据和具体诉求（至少 10 个字符）"></textarea></label></div><div class="hr12-action-toolbar"><button class="hr12-action-btn" type="button" data-submit-objection>提交结果异议</button></div>` : ''}
      ${actions.canDecideObjection ? `<div data-objection-decision data-objection-id="${esc(objection.id)}"><div class="hr12-action-field"><label>复核决定<select data-decision-code><option value="REJECTED">异议驳回</option><option value="MODIFIED">部分调整</option><option value="UPHELD">异议成立</option></select></label></div><div class="hr12-action-field"><label>复核结论<textarea data-decision-conclusion rows="4" minlength="10" maxlength="4000" placeholder="写明复核事实、制度依据和处理结论"></textarea></label></div><div class="hr12-action-field"><label>调整后档次（成立/调整时必填）<select data-corrected-grade><option value="">请选择</option><option value="EXCELLENT">优秀</option><option value="QUALIFIED">合格</option><option value="BASIC_QUALIFIED">基本合格</option><option value="UNQUALIFIED">不合格</option></select></label></div><div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="button" data-decide-objection>复核结案</button></div></div>` : ''}
      ${actions.canArchive ? '<div class="hr12-action-toolbar"><button class="hr12-action-btn primary" type="button" data-archive-result>核验条件并正式归档</button></div>' : ''}
    </article>`;
  }

  async function mountResultLifecycle() {
    if (section !== 'archive' || root.querySelector('[data-result-lifecycle]')) return;
    const host = document.createElement('section');
    host.className = 'hr12-action-card';
    host.dataset.resultLifecycle = 'true';
    host.innerHTML = `<h2>结果告知、异议与归档</h2><p>按国内高校常用顺序办理：结果告知并留回执、本人确认或提出异议、复核结案、正式归档。</p><div class="hr12-action-result" data-review-result role="status" aria-live="polite"></div><div class="hr12-action-grid" data-lifecycle-items></div>`;
    root.querySelector('.hr12-principle')?.before(host);
    const itemsHost = host.querySelector('[data-lifecycle-items]');
    async function refresh() {
      try {
        const value = await getJson('/api/v1/hr/assessments/results/lifecycle');
        const items = Array.isArray(value) ? value : [];
        itemsHost.innerHTML = items.length ? items.map(lifecycleItemHtml).join('') : '<div class="hr12-action-note">当前学校暂无可办理的正式考核结果。</div>';
      } catch (error) {
        itemsHost.innerHTML = `<div class="hr12-action-note">${esc(error.message || '结果生命周期读取失败')}</div>`;
      }
    }
    host.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-issue-notice], [data-confirm-delivery], [data-acknowledge], [data-submit-objection], [data-decide-objection], [data-archive-result]');
      if (!button) return;
      const card = button.closest('[data-lifecycle-result]');
      const resultId = card?.dataset.lifecycleResult;
      if (!resultId) return;
      button.disabled = true;
      try {
        if (button.matches('[data-issue-notice]')) {
          await postJson(`/api/v1/hr/assessments/results/${resultId}/notices`, {deliveryChannel: 'SYSTEM'});
          reviewMessage(host, '结果告知单已生成，下一步请登记真实送达回执。');
        } else if (button.matches('[data-confirm-delivery]')) {
          await postJson(`/api/v1/hr/assessments/notices/${button.dataset.noticeId}/delivery`, {
            deliveryReceiptRef: card.querySelector('[data-delivery-receipt]')?.value || '',
          });
          reviewMessage(host, '结果送达回执已登记。');
        } else if (button.matches('[data-acknowledge]')) {
          await postJson(`/api/v1/hr/assessments/results/${resultId}/acknowledgements`, {
            acknowledgementStatus: card.querySelector('[data-ack-status]')?.value,
            employeeOpinion: card.querySelector('[data-ack-opinion]')?.value || '',
          });
          reviewMessage(host, '本人意见已确认并留痕。');
        } else if (button.matches('[data-submit-objection]')) {
          await postJson(`/api/v1/hr/assessments/results/${resultId}/objections`, {
            reason: card.querySelector('[data-objection-reason]')?.value || '',
            evidenceRefs: [],
          });
          reviewMessage(host, '结果异议已正式提交，归档将在复核结案前阻断。');
        } else if (button.matches('[data-decide-objection]')) {
          const panel = button.closest('[data-objection-decision]');
          const decisionCode = panel.querySelector('[data-decision-code]')?.value;
          const gradeCode = panel.querySelector('[data-corrected-grade]')?.value;
          const gradeLabels = {EXCELLENT: '优秀', QUALIFIED: '合格', BASIC_QUALIFIED: '基本合格', UNQUALIFIED: '不合格'};
          if (decisionCode !== 'REJECTED' && !gradeCode) throw new Error('异议成立或部分调整时必须选择调整后档次');
          await postJson(`/api/v1/hr/assessments/objections/${panel.dataset.objectionId}/decision`, {
            decisionCode,
            conclusion: panel.querySelector('[data-decision-conclusion]')?.value || '',
            expectedVersion: Number(card.dataset.resultVersion || 1),
            changes: decisionCode === 'REJECTED' ? {} : {
              gradeCode,
              displayGrade: {'zh-CN': gradeLabels[gradeCode]},
            },
          });
          reviewMessage(host, decisionCode === 'REJECTED' ? '异议已驳回复核并结案。' : '异议已结案，正式结果更正版已同步封存。');
        } else {
          await postJson(`/api/v1/hr/assessments/results/${resultId}/archive`, {documentRefs: []});
          reviewMessage(host, '考核结果已核验并正式归档。');
        }
        await refresh();
        loadAuthorityWorkbench();
      } catch (error) { reviewMessage(host, error.message || '办理失败', true); }
      finally { button.disabled = false; }
    });
    await refresh();
  }

  function renderSection(policies, indicators) {
    const title = document.getElementById('workTitle');
    const description = document.getElementById('workDesc');
    const box = document.getElementById('workRows');
    if (!title || !description || !box) return;

    if (section === 'policies') {
      title.textContent = '制度与指标';
      description.textContent = '考核制度、指标和评分量表按版本管理；正式发布后保留历史。';
      const policyRows = policies.map((item) => row(item.name, item.code, item.assessment_domain === 'TERM' ? '聘期考核' : '年度/专项考核', item.status || '—'));
      const indicatorRows = indicators.slice(0, 12).map((item) => row(item.name, item.code, item.dimension || '考核指标', item.status || '—'));
      const merged = [...policyRows, ...indicatorRows];
      box.innerHTML = merged.length ? merged.join('') : empty('暂无考核制度或指标', '当前学校还没有可展示的考核制度或有效指标事实。');
      return;
    }

    if (section === 'annual') {
      title.textContent = '年度考核';
      description.textContent = '先锁定当前考核对象的证据快照，再基于已完成审定会形成可追溯的正式结果。';
      box.innerHTML = empty('正在读取年度考核', '正在核对当前学校年度考核对象、证据快照和审定状态。');
      loadAnnualCases();
      return;
    }

    const authoritySections = {
      goals: ['目标任务与平时考核', '读取当前学校的目标版本、目标计划、承担人数和正式状态。'],
      term: ['聘期考核', '聘期案件与年度案件分开呈现，保留独立周期和状态。'],
      ethics: ['师德与专项考核', '仅呈现独立师德案件的事实来源、Gate 状态和原因，不从其它评价推断。'],
      review: ['评议与审定', '校准会与正式审定会分权呈现，保留会议状态和修订数量。'],
      archive: ['结果与考核档案', '读取正式结果版本、归档状态和异议数量，确保结果链可追溯。'],
    };
    if (authoritySections[section]) {
      const [sectionTitle, sectionDescription] = authoritySections[section];
      title.textContent = sectionTitle;
      description.textContent = sectionDescription;
      box.innerHTML = empty('正在读取正式业务事实', '正在按当前学校和校级统计权限核对数据。');
      loadAuthorityWorkbench();
      if (section === 'review') mountReviewWorkbench();
      if (section === 'archive') mountResultLifecycle();
      return;
    }

    title.textContent = '制度与指标概览';
    description.textContent = '先确认考核依据，再进入目标、年度、聘期、师德和评议工作区。';
    const merged = [
      ...policies.slice(0, 4).map((item) => row(item.name, item.code, '考核制度', item.status || '—')),
      ...indicators.slice(0, 4).map((item) => row(item.name, item.code, item.dimension || '考核指标', item.status || '—')),
    ];
    box.innerHTML = merged.length ? merged.join('') : empty('暂无可展示的考核依据', '当前学校尚未配置可读取的考核制度或指标。');
  }

  function renderReadiness(state) {
    if (section !== 'overview') return;
    const title = document.getElementById('readinessTitle');
    const summary = document.getElementById('readinessSummary');
    if (!title || !summary) return;
    if (state.policyLoaded && state.policies.length === 0) {
      title.textContent = '尚未形成可展示的考核制度';
      summary.textContent = '建议先从“制度与指标”确认学校考核依据；页面不会用默认制度替代真实配置。';
      return;
    }
    if (state.sourceLoaded && Object.values(state.sources).some((value) => value !== 'OK')) {
      title.textContent = '部分业务来源仍需确认';
      summary.textContent = '考核依据已读取，但部分来源为“部分可用”或“暂不可用”；进入正式考核前应先确认数据边界。';
      return;
    }
    if (state.policyLoaded && state.indicatorLoaded && state.scaleLoaded && state.sourceLoaded) {
      title.textContent = '当前考核依据与来源状态已读取';
      summary.textContent = `已读取 ${state.policies.length} 套制度、${state.indicators.length} 个指标、${state.scales.length} 个量表；可按业务链进入相应工作区。`;
      return;
    }
    title.textContent = '仍有考核依据或来源状态无法读取';
    summary.textContent = '当前存在未知状态；页面不会把读取失败自动显示成 0 条、0 分或“全部正常”。';
  }

  async function boot() {
    const [policyResult, indicatorResult, scaleResult, sourceResult] = await Promise.allSettled([
      getJson('/api/v1/hr/assessments/policies'),
      getJson('/api/v1/hr/assessments/indicators'),
      getJson('/api/v1/hr/assessments/rating-scales'),
      getJson('/api/v1/hr/assessments/eligibility'),
    ]);

    const policyLoaded = policyResult.status === 'fulfilled';
    const indicatorLoaded = indicatorResult.status === 'fulfilled';
    const scaleLoaded = scaleResult.status === 'fulfilled';
    const sourceLoaded = sourceResult.status === 'fulfilled';
    const policies = policyLoaded && Array.isArray(policyResult.value) ? policyResult.value : [];
    const indicators = indicatorLoaded && Array.isArray(indicatorResult.value) ? indicatorResult.value : [];
    const scales = scaleLoaded && Array.isArray(scaleResult.value) ? scaleResult.value : [];
    const sourcePayload = sourceLoaded && sourceResult.value && typeof sourceResult.value === 'object'
      ? sourceResult.value
      : {};
    const sources = sourcePayload.providerStatus && typeof sourcePayload.providerStatus === 'object'
      ? sourcePayload.providerStatus
      : {};

    const policyCount = document.getElementById('policyCount');
    const indicatorCount = document.getElementById('indicatorCount');
    const scaleCount = document.getElementById('scaleCount');
    const sourceHealth = document.getElementById('sourceHealth');
    const sourceHealthCard = document.getElementById('sourceHealthCard');
    if (policyCount) policyCount.textContent = policyLoaded ? String(policies.length) : '—';
    if (indicatorCount) indicatorCount.textContent = indicatorLoaded ? String(indicators.length) : '—';
    if (scaleCount) scaleCount.textContent = scaleLoaded ? String(scales.length) : '—';

    const values = Object.values(sources);
    if (sourceHealth) {
      if (!sourceLoaded) sourceHealth.textContent = '—';
      else if (!values.length) sourceHealth.textContent = '暂无状态';
      else if (values.every((value) => value === 'OK')) sourceHealth.textContent = '全部正常';
      else {
        sourceHealth.textContent = `${values.filter((value) => value === 'OK').length}/${values.length} 已接通`;
        sourceHealthCard?.classList.add('hr12-kpi--warning');
      }
    }

    const sourceStatus = document.getElementById('sourceStatus');
    if (sourceStatus) {
      if (!sourceLoaded) sourceStatus.innerHTML = '<div class="hr12-status-note">当前无法读取数据接入状态；未知状态不会当作正常。</div>';
      else if (!Object.keys(sources).length) sourceStatus.innerHTML = '<div class="hr12-status-note">当前学校暂无可展示的数据来源状态。</div>';
      else sourceStatus.innerHTML = Object.entries(sources).map(([key, value]) => {
        const className = value === 'OK' ? 'hr12-ok' : (value === 'PARTIAL' ? 'hr12-partial' : 'hr12-off');
        return `<div class="hr12-cap"><span>${esc(sourceNames[key] || key)}</span><b class="${className}">${esc(zhStatus[value] || value || '暂不可用')}</b></div>`;
      }).join('');
    }

    renderSection(policies, indicators);
    renderReadiness({policyLoaded, indicatorLoaded, scaleLoaded, sourceLoaded, policies, indicators, scales, sources});
  }

  root.addEventListener('click', handleAnnualAction);
  // Start immediately after the HR12 root is mounted. Each provider read is
  // independently bounded above, so one slow/unavailable source cannot leave
  // the whole workspace permanently stuck in the initial loading state.
  boot();
  mountAnnualSetup();
})();
