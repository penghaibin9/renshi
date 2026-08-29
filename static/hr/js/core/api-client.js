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

  function apiErrorToMessage(err) {
    if (err && err.data && err.data.error && err.data.error.message) {
      return err.data.error.message;
    }
    const map = {
      TENANT_CONTEXT_REQUIRED: "请先选择当前学校",
      PERMISSION_DENIED: "无权限查看",
      SCOPE_NOT_ALLOWED: "当前数据范围不允许",
      PROVIDER_UNAVAILABLE: "数据暂不可用",
      TIMEOUT_OR_ABORTED: "请求超时",
    };
    return (err && err.code && map[err.code]) || "数据加载失败";
  }

  window.HrApi = {
    request,
    apiErrorToMessage,
  };
})(window);
