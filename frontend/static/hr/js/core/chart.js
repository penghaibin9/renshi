/**
 * hr-core/chart.js — HrChart wrapper
 *
 * 总册 9.5：ApexCharts 固定版本、本地静态托管、通过 wrapper 使用；
 * 页面不得直接写 ApexCharts option 大对象；支持 table fallback；
 * 颜色从 semantic palette 取，不允许业务页面随意指定随机颜色。
 */
(function (window) {
  "use strict";

  // 语义色板（禁止业务页面传随机颜色）
  const PALETTE = {
    primary: "#2563eb",
    success: "#16a34a",
    warning: "#d97706",
    danger: "#dc2626",
    info: "#0284c7",
    text: "#64748b",
    grid: "rgba(0,0,0,0.06)",
  };

  function isDark() {
    return document.documentElement.classList.contains("dark");
  }

  /**
   * @param {HTMLElement|string} el 容器（id 或元素）
   * @param {object} config { type, categories, series:[{name,data}], horizontal, height }
   * @returns {object} { instance, render() }
   */
  function createChart(el, config) {
    if (typeof window.ApexCharts === "undefined") {
      console.error("HrChart: ApexCharts 未加载（应本地静态托管）");
      return null;
    }
    const container = typeof el === "string" ? document.getElementById(el) : el;
    if (!container) return null;

    const dark = isDark();
    const palette = dark
      ? { ...PALETTE, text: "#94a3b8", grid: "rgba(255,255,255,0.06)" }
      : PALETTE;

    const base = {
      chart: {
        type: config.type || "bar",
        height: config.height || 280,
        toolbar: { show: false },
        background: "transparent",
        fontFamily: "inherit",
        events: config.events || {},
      },
      colors: config.colors || [palette.primary],
      dataLabels: config.dataLabels || { enabled: false },
      tooltip: { theme: dark ? "dark" : "light" },
      legend: config.legend || { show: false },
    };

    if (config.type === "bar") {
      base.plotOptions = {
        bar: {
          horizontal: !!config.horizontal,
          borderRadius: 6,
          distributed: !!config.distributed,
        },
      };
      base.xaxis = {
        categories: config.categories || [],
        labels: { style: { colors: palette.text, fontSize: "11px" } },
        axisBorder: { show: false },
        axisTicks: { show: false },
      };
      base.yaxis = { labels: { style: { colors: palette.text, fontSize: "11px" } } };
      base.grid = { borderColor: palette.grid, strokeDashArray: 4 };
    } else if (config.type === "line" || config.type === "area") {
      base.stroke = { curve: "smooth", width: 2 };
      base.xaxis = {
        categories: config.categories || [],
        labels: { style: { colors: palette.text, fontSize: "11px" } },
      };
      base.yaxis = { labels: { style: { colors: palette.text } } };
      base.grid = { borderColor: palette.grid, strokeDashArray: 4 };
      if (config.type === "area") base.fill = { type: "gradient" };
    }

    const series = (config.series || []).map((s) => ({ ...s }));

    const instance = new window.ApexCharts(container, {
      ...base,
      series,
    });

    return { instance, render: () => instance.render() };
  }

  window.HrChart = {
    createChart,
    PALETTE,
  };
})(window);
