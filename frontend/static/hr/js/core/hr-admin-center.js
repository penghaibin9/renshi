/* 学校系统管理：任务搜索、管理员提示词、实施进度与高风险权限防误点 */
(() => {
  "use strict";
  const center = document.querySelector("[data-system-admin-center]");
  const normalise = (value) => String(value || "").toLowerCase().replace(/\s+/g, "");

  const ANSWERS = {
    "单校版第一次上线先配置什么？":"按 6 步走：学校主体 → 组织岗位 → 管理员角色 → 基础参数/通知 → 安全审计 → 备份恢复演练。单校版只有一个学校主体，学院和部门应建在组织树里，不要再建第二个学校。",
    "学院和部门应该建在哪里？":"学校主体只保留一所学校。二级学院、职能部门、系部等都进入“组织与部门”；岗位进入“岗位与职务”。不要把学院当成第二个 Company/学校主体，否则权限范围和统计口径会变复杂。",
    "怎么给新管理员分配最小权限？":"先复制最接近的学校角色模板，再只保留完成职责所需权限和数据范围。日常管理员优先使用系统管理员角色，不长期使用超级管理员。",
    "复制角色后哪些东西不会被复制？":"只复制 Permission 权限集合；成员、学校/组织数据范围、个人直接权限不会跟着复制，必须在目标角色上重新核对。",
    "为什么不建议给个人直接加权限？":"个人直接权限难以批量复核和回收。优先通过角色授权；确有例外时再单独授权，并在审计中保留原因和复核日期。",
    "怎么判断一个账号是不是权限过大？":"先看角色，再看个人直接权限、数据范围和高风险 Delete/授权类权限。能用普通角色完成工作的，不应继续保留超级管理员或额外直接权限。",
    "组织调整后权限范围怎么处理？":"组织事实由组织模块维护；角色权限与数据范围应随正式组织关系重新核对。不要通过修改人员主档或前端隐藏来替代后端权限范围。",
    "接口同步失败应该先查什么？":"先看最近同步时间、失败原因、字段映射和幂等键，再决定单条重试或批量补传。发送成功不等于对方已回执/对账成功。",
    "什么时候必须做备份恢复演练？":"正式上线前、重大升级前、数据库迁移前以及学校要求的周期性演练时。仅生成备份文件不算完成，必须在隔离空环境验证可恢复。",
    "安全审计员和系统管理员有什么区别？":"系统管理员负责账号、角色、组织和配置；安全审计员以只读方式检查登录、权限、敏感访问、导出和配置变更，不应同时拥有日常修改权限。",
    "哪些设置改了会影响历史业务？":"权限、考核/薪酬规则、接口字段映射、关键字典和历史口径都可能影响业务解释。历史正式结果应依赖版本/快照，不能因修改当前配置被静默改写。",
    "正式上线前系统管理还要检查什么？":"至少核对管理员账号、角色数据范围、组织岗位、关键字典、真实接口、审计、安全策略、备份恢复、初始化快照和最终验收证据。",
    "我只想改一个设置，最短怎么走？":"在本页‘我要设置什么’直接输入目的，例如‘改日期格式’‘查权限’‘邮件’，只进入对应设置。保存前确认当前学校/单位范围，避免改错范围。"
  };

  if (center) {
    const input = center.querySelector("#sysadmin-task-search");
    const results = center.querySelector("#sysadmin-search-results");
    const cards = Array.from(center.querySelectorAll(".sysadmin-task-card"));
    function renderSearch() {
      if (!input || !results) return;
      const q = normalise(input.value);
      if (!q) { results.hidden = true; results.innerHTML = ""; return; }
      const matched = cards.filter((card) => normalise(`${card.dataset.title} ${card.dataset.keywords} ${card.textContent}`).includes(q));
      results.innerHTML = "";
      matched.slice(0, 8).forEach((card) => {
        const a = document.createElement("a");
        a.className = "sysadmin-search-item";
        a.href = card.getAttribute("href");
        a.innerHTML = `<span class="sysadmin-task-icon">↗</span><span><strong>${card.dataset.title}</strong><small>${card.querySelector("small")?.textContent || ""}</small></span>`;
        results.append(a);
      });
      if (!matched.length) results.innerHTML = '<div class="sysadmin-search-item"><span><strong>没有直接匹配</strong><small>换成“账号、角色、组织、审计、邮件、接口、备份”等业务词再试。</small></span></div>';
      results.hidden = false;
    }
    input?.addEventListener("input", renderSearch);
    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement?.tagName || "")) {
        event.preventDefault(); input?.focus();
      }
      if (event.key === "Escape" && document.activeElement === input) { input.value = ""; renderSearch(); input.blur(); }
    });

    // Only the implementation MEMO uses browser storage. The first-use panel
    // is server-rendered and has no client-side completion mutation.
    const schoolKey = center.dataset.schoolScope || "unbound";
    const storageKey = "yueke.hr.sysadmin.onboarding.v2" + ":memo:" + schoolKey;
    let state = {};
    try { state = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_) { state = {}; }
    center.querySelectorAll(".sysadmin-checklist li[data-check]").forEach((row) => {
      const key = row.dataset.check;
      if (state[key]) row.classList.add("is-done");
      row.querySelector("button")?.addEventListener("click", () => {
        row.classList.toggle("is-done"); state[key] = row.classList.contains("is-done");
        try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) {}
      });
    });
    const answer = center.querySelector("#sysadmin-answer");
    center.querySelectorAll(".sysadmin-prompts button").forEach((button) => button.addEventListener("click", () => {
      if (!answer) return;
      answer.textContent = ANSWERS[button.textContent.trim()] || "请从系统管理首页按任务入口进入对应设置，并在保存前核对当前学校/单位范围。";
      answer.hidden = false;
    }));
  }

  function permissionRiskSummary(root) {
    const box = root.querySelector(".sysadmin-role-risk");
    if (!box) return;
    const checked = Array.from(root.querySelectorAll('input[name="permissions"]:checked'));
    const high = checked.filter((el) => el.dataset.permissionRisk === "high");
    box.textContent = `当前已授权 ${checked.length} 项${high.length ? `，其中高风险 ${high.length} 项` : "，未发现 Delete 类高风险权限"}。保存前请同时核对成员和数据范围。`;
    box.classList.toggle("is-danger", high.length > 0);
  }

  document.addEventListener("change", (event) => {
    const input = event.target.closest?.('input[name="permissions"]');
    if (!input) return;
    if (input.checked && input.dataset.permissionRisk === "high") {
      const ok = window.confirm("这是高风险删除权限。确认该角色确实需要删除业务数据的能力吗？\n\n建议优先只授予查看/办理权限，并由最少角色持有删除能力。");
      if (!ok) { input.checked = false; input.dispatchEvent(new Event("change", {bubbles:false})); return; }
    }
    const panel = input.closest(".ug-tab-panel") || input.closest("form") || document;
    permissionRiskSummary(panel);
  }, true);
  document.querySelectorAll(".ug-tab-panel, form.perm-form").forEach(permissionRiskSummary);
})();
