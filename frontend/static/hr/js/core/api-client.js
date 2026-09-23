/**
 * hr-core/api-client.js — HR01 统一 API 客户端
 *
 * 处理：CSRF / 401 / 403 / 409 / 422 / 429 / 5xx / requestId / abort / timeout / retry（仅安全 GET）。
 * 前端根据 error.code 显示可解释状态，不根据英文 message 写业务判断。
 */
(function (window) {
  "use strict";

  const DEFAULT_TIMEOUT_MS = 15000;

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  /**
   * @param {string} url
   * @param {object} options { method, params, body, headers, timeoutMs, signal, retries }
   * @returns {Promise<{ok:boolean, status:number, data:any, requestId?:string, code?:string}>}
   */
  async function request(url, options = {}) {
    const {
      method = "GET",
      params = null,
      body = null,
      headers: customHeaders = {},
      timeoutMs = DEFAULT_TIMEOUT_MS,
      signal = null,
      retries = 0,
    } = options;

    let target = url;
    if (params) {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") qs.set(k, v);
      });
      const s = qs.toString();
      if (s) target += (target.includes("?") ? "&" : "?") + s;
    }

    const requestHeaders = {
      ...customHeaders,
      "X-Requested-With": "XMLHttpRequest",
    };
    if (body && !requestHeaders["Content-Type"]) {
      requestHeaders["Content-Type"] = "application/json";
    }

    const csrf = getCookie("csrftoken");
    if (csrf) requestHeaders["X-CSRFToken"] = csrf;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const signals = [controller.signal];
    if (signal) signals.push(signal);

    let attempt = 0;
    let lastError = null;

    while (attempt <= retries) {
      if (attempt > 0) {
        // 简单退避：仅安全 GET 允许有限重试
        await new Promise((r) => setTimeout(r, 300 * attempt));
      }
      attempt += 1;

      try {
        const combined = new AbortController();
        signals.forEach((s) => {
          if (s.aborted) combined.abort();
          s.addEventListener("abort", () => combined.abort());
        });

        const resp = await fetch(target, {
          method,
          headers: requestHeaders,
          body: body ? JSON.stringify(body) : null,
          signal: combined.signal,
          credentials: "same-origin",
        });

        let data = null;
        const ct = resp.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          data = await resp.json();
        }

        if (!resp.ok) {
          const err = new Error(`HTTP ${resp.status}`);
          err.status = resp.status;
          err.data = data;
          err.requestId = data && data.requestId;
          err.code =
            (data && data.error && data.error.code) || defaultCode(resp.status);
          lastError = err;
          if (retryable(resp.status) && attempt <= retries) {
            continue;
          }
          throw err;
        }

        clearTimeout(timeoutId);
        return {
          ok: true,
          status: resp.status,
          data,
          requestId: data && data.requestId,
        };
      } catch (e) {
        if (e.name === "AbortError") {
          clearTimeout(timeoutId);
          e.status = 408;
          e.code = "TIMEOUT_OR_ABORTED";
          throw e;
        }
        lastError = e;
        if (retryable(0) && attempt <= retries) {
          continue;
        }
        clearTimeout(timeoutId);
        throw e;
      }
    }

    throw lastError;
  }

  function retryable(status) {
    // 仅安全 GET 重试：429 / 503 / 网络错误
    return status === 429 || status === 503 || status === 0;
  }

  function defaultCode(status) {
    const map = {
      400: "INVALID_REQUEST",
      401: "UNAUTHENTICATED",
      403: "PERMISSION_DENIED",
      404: "RESOURCE_NOT_FOUND",
      409: "VERSION_CONFLICT",
      422: "BUSINESS_RULE_VIOLATION",
      429: "RATE_LIMITED",
      500: "INTERNAL_ERROR",
      503: "PROVIDER_UNAVAILABLE",
    };
    return map[status] || "UNKNOWN_ERROR";
  }

  const ERROR_GUIDANCE = {
    TENANT_CONTEXT_REQUIRED: {
      message: "还没选择当前学校",
      action: "先切换到要办理的学校，再重新进入当前页面。",
    },
    PERMISSION_DENIED: {
      message: "当前账号没有这项操作权限",
      action: "确认当前角色和数据范围；确需办理时联系学校管理员授权。",
    },
    SCOPE_NOT_ALLOWED: {
      message: "这条数据不在当前可处理范围",
      action: "确认所属学院/部门和当前数据范围，不要通过修改地址绕过权限。",
    },
    PROVIDER_UNAVAILABLE: {
      message: "业务数据暂时不可用",
      action: "可先处理其他事项，稍后重试；持续失败时把请求号提供给管理员。",
    },
    TIMEOUT_OR_ABORTED: {
      message: "请求超时，本次操作是否成功还不能确认",
      action: "先刷新业务状态，再决定是否重试，避免重复提交。",
    },
    INVALID_REQUEST: {
      message: "还有内容不完整或格式不正确",
      action: "按页面必填/标红提示补充后再提交。",
    },
    UNAUTHENTICATED: {
      message: "登录状态已失效",
      action: "重新登录后回到原业务页面继续办理。",
    },
    RESOURCE_NOT_FOUND: {
      message: "没有找到这条业务记录",
      action: "请从对应台账重新搜索进入；不要继续使用旧收藏或过期链接。",
    },
    VERSION_CONFLICT: {
      message: "这条数据刚被其他人更新",
      action: "刷新页面并核对最新状态后再提交，不要覆盖他人的新结果。",
    },
    BUSINESS_RULE_VIOLATION: {
      message: "当前业务状态还不能执行这一步",
      action: "先完成页面提示的前置步骤或待办，再回来继续。",
    },
    RATE_LIMITED: {
      message: "操作过于频繁",
      action: "请稍后再试，不要连续点击提交按钮。",
    },
    INTERNAL_ERROR: {
      message: "系统处理失败",
      action: "先不要重复提交；刷新状态后仍失败时，把请求号提供给管理员排查。",
    },
    UNKNOWN_ERROR: {
      message: "数据暂时没有加载成功",
      action: "先刷新页面；仍失败时记录发生时间和请求号，再联系管理员。",
    },
  };

  function apiErrorToGuidance(err) {
    const code = (err && err.code) || "UNKNOWN_ERROR";
    const base = ERROR_GUIDANCE[code] || ERROR_GUIDANCE.UNKNOWN_ERROR;
    const detail = err && err.data && err.data.error && err.data.error.message;
    const requestId = (err && err.requestId) || (err && err.data && err.data.requestId) || null;

    // 服务端明确返回中文业务原因时保留原原因；下一步动作仍由统一前端口径补充。
    const message = detail && /[\u3400-\u9fff]/.test(detail) ? detail : base.message;
    return { code, message, action: base.action, requestId };
  }

  function apiErrorToMessage(err) {
    const guidance = apiErrorToGuidance(err);
    return `${guidance.message}。${guidance.action}`;
  }

  const STATUS_LABELS = {
    DRAFT: "草稿", SUBMITTED: "已提交", UNDER_REVIEW: "审核中", RETURNED: "已退回",
    REJECTED: "已驳回", APPROVED: "已批准", PENDING: "待处理", READY: "就绪",
    ACTIVE: "有效", INACTIVE: "停用", SCHEDULED: "已预约", REPORTED: "已报到",
    EFFECTIVE: "已生效", CANCELLED: "已取消", COMPLETED: "已完成", FAILED: "失败",
    NOT_STARTED: "未开始", IN_PROGRESS: "进行中", WAITING_EXTERNAL: "等待外部处理",
    BLOCKED: "已阻塞", WAIVED: "已豁免", VERIFIED: "已核验", UNVERIFIED: "未核验",
    MISSING: "缺失", EXPIRED: "已过期", PASSED: "已通过", QUALIFIED: "资格通过",
    DISQUALIFIED: "资格不符", MATCHED: "已匹配", UNMATCHED: "未匹配", CONFLICT: "存在冲突",
    SUCCESS: "成功", RUNNING: "处理中", OPEN: "开放中", CLOSED: "已关闭",
  };

  function statusLabel(value, provided, fallback = "状态待确认") {
    return provided || STATUS_LABELS[String(value || "").toUpperCase()] || fallback;
  }

  window.HrApi = {
    request,
    apiErrorToMessage,
    apiErrorToGuidance,
    statusLabel,
  };
})(window);
