// HR10 发展模块前端脚本（中文）
// 加载 Dashboard / 列表数据

const HR10 = {
  // 通用 API 请求（自动带 tenant 上下文）
  async fetchJson(url, options = {}) {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    return resp.json();
  },

  // 加载教师发展档案摘要
  async loadRecordOverview(staffId) {
    const data = await this.fetchJson(`/api/v1/hr/development/development-records/${staffId}`);
    if (data.error) {
      document.getElementById("record-error").textContent = "教师发展档案加载失败，请稍后重试。";
      return;
    }
    const el = document.getElementById("record-overview");
    if (el) {
      el.innerHTML = `
        <div class="stats">
          <div class="stat-card"><div class="label">培训完成</div><div class="value">${data.data.trainingCompletions}</div></div>
          <div class="stat-card"><div class="label">进修</div><div class="value">${data.data.furtherStudies}</div></div>
          <div class="stat-card"><div class="label">企业实践</div><div class="value">${data.data.enterprisePractices}</div></div>
          <div class="stat-card"><div class="label">已核验成果</div><div class="value">${data.data.developmentOutputs}</div></div>
          <div class="stat-card"><div class="label">累计学时</div><div class="value">${data.data.totalVerifiedHours}</div></div>
          <div class="stat-card"><div class="label">累计实践天数</div><div class="value">${data.data.totalVerifiedDays}</div></div>
        </div>`;
    }
  },

  // 加载 Dashboard 指标
  async loadDashboard() {
    const data = await this.fetchJson("/api/v1/hr/development/dashboard");
    if (data.error) return;
    const cards = document.querySelectorAll(".stat-card .value");
    if (data.data && data.data.metrics && cards.length >= 5) {
      cards[0].textContent = data.data.metrics[0].value;
      cards[1].textContent = data.data.metrics[1].value;
      cards[2].textContent = data.data.metrics[2].value;
      cards[3].textContent = data.data.metrics[3].value;
      cards[4].textContent = data.data.metrics[4].value;
    }
  },

  // 加载发展计划列表
  async loadPlans() {
    const data = await this.fetchJson("/api/v1/hr/development/plans");
    if (data.error) return;
    const tbody = document.querySelector("#plans-table tbody");
    if (tbody && data.data) {
      tbody.innerHTML = data.data.map(p => `
        <tr>
          <td>${p.planNo}</td>
          <td>${p.planTypeLabel}</td>
          <td>${p.cycleType}</td>
          <td>${p.startDate || ""}</td>
          <td>${p.endDate || ""}</td>
          <td><span class="badge">${p.lifecycleStatusLabel}</span></td>
        </tr>`).join("");
    }
  },
};

document.addEventListener("DOMContentLoaded", () => {
  // 自动初始化
  const body = document.body.dataset;
  if (body.page === "dashboard") HR10.loadDashboard();
  if (body.page === "plans") HR10.loadPlans();
  if (body.recordId) HR10.loadRecordOverview(body.recordId);
});
