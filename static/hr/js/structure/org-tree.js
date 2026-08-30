/**
 * hr-structure/org-tree.js — HrOrgTree：懒加载 + 键盘导航 + 搜索定位 + 稳定 id 恢复选中
 *
 * 依赖：无（自带 fetch；若页面已加载 hr-core/api-client.js，则优先使用 window.HrApi）。
 *
 * 行为：
 *  - 懒加载：展开有子节点的行时，按 tree_api_url 拉取其 children（每层一次请求）；
 *  - 键盘：↑/↓ 移动、←/→ 收起/展开、Home/End 到首/末、Enter 进入详情、字符键入定位；
 *  - 搜索：输入关键词后高亮匹配、自动展开祖先、聚焦首个匹配，Esc 清空；
 *  - 稳定 id：data-selected-id 命中的节点加 is-selected 并滚动到可视区。
 *
 * 用法：
 *  <script src="{% static 'hr/js/structure/org-tree.js' %}"></script>
 *  页面 DOM 就绪后调用 HrOrgTree.initAll()（脚本加载即自动注册 DOMContentLoaded）。
 */
(function (window, document) {
  "use strict";

  var API = window.HrApi;

  function qsa(root, sel) {
    return Array.prototype.slice.call(root.querySelectorAll(sel));
  }

  function isVisible(row) {
    var el = row;
    while (el && el !== document.body && el !== document) {
      if (el.hidden) return false;
      el = el.parentElement;
    }
    return true;
  }

  function treeRootOf(row) {
    return row.closest ? row.closest(".hr-org-tree") : null;
  }

  function buildChildrenUrl(base, id, asOf, dimension) {
    var url = base.indexOf("{id}") !== -1
      ? base.replace("{id}", encodeURIComponent(id))
      : base + (base.indexOf("?") !== -1 ? "&" : "?") + "parent_id=" + encodeURIComponent(id);
    var u = new URL(url, window.location.origin);
    if (asOf) u.searchParams.set("asOf", asOf);
    if (dimension) u.searchParams.set("dimension", dimension);
    return u.toString();
  }

  function getChildrenUl(row) {
    var item = row.parentElement;
    if (!item) return null;
    return item.querySelector(".hr-org-tree__children");
  }

  function setTwistyLeaf(row) {
    var t = row.querySelector(".hr-org-tree__twisty");
    if (t) t.classList.add("hr-org-tree__twisty--leaf");
  }

  function buildNode(n, parentRow) {
    // 与 org_tree.html 的行结构保持一致，保证懒加载子树可继续懒加载
    var li = document.createElement("li");
    li.className = "hr-org-tree__item";
    li.setAttribute("role", "none");

    var row = document.createElement("div");
    row.className = "hr-org-tree__row";
    row.setAttribute("role", "treeitem");
    row.setAttribute("tabindex", "-1");
    row.dataset.nodeId = n.id != null ? String(n.id) : "";
    row.dataset.nodeCode = n.stable_code || "";
    row.dataset.nodeUrl = n.url || "";
    row.dataset.search = String(n.name || "").toLowerCase();
    row.dataset.hasChildren = n.has_children ? "true" : "false";
    row.dataset.loaded = "false";
    row.setAttribute(
      "aria-level",
      String(parseInt(parentRow.getAttribute("aria-level"), 10) + 1)
    );
    row.setAttribute("aria-expanded", "false");
    row.setAttribute("aria-selected", "false");
    if (n.status === "PENDING") row.classList.add("is-pending");
    if (n.status === "INACTIVE") row.classList.add("is-inactive");

    var twisty = document.createElement("span");
    twisty.className = "hr-org-tree__twisty";
    twisty.setAttribute("aria-hidden", "true");
    twisty.textContent = "\u25B6";
    row.appendChild(twisty);

    var a = document.createElement("a");
    a.className = "hr-org-tree__label";
    a.href = n.url || "#";
    a.appendChild(document.createTextNode(n.name != null ? String(n.name) : ""));
    row.appendChild(a);

    if (n.stable_code) {
      var code = document.createElement("span");
      code.className = "hr-org-tree__code";
      code.appendChild(document.createTextNode(String(n.stable_code)));
      row.appendChild(code);
    }
    if (n.type_label) {
      var t = document.createElement("span");
      t.className = "hr-org-tree__type";
      t.appendChild(document.createTextNode(String(n.type_label)));
      row.appendChild(t);
    }
    if (n.status === "PENDING") {
      var sp = document.createElement("span");
      sp.className = "hr-org-tree__status hr-org-tree__status--pending";
      sp.appendChild(document.createTextNode("\u5F85\u751F\u6548")); // 待生效
      row.appendChild(sp);
    } else if (n.status === "INACTIVE") {
      var si = document.createElement("span");
      si.className = "hr-org-tree__status hr-org-tree__status--inactive";
      si.appendChild(document.createTextNode("\u5DF2\u505C\u7528")); // 已停用
      row.appendChild(si);
    }

    li.appendChild(row);

    if (n.has_children) {
      var ul = document.createElement("ul");
      ul.className = "hr-org-tree__children";
      ul.setAttribute("role", "group");
      ul.hidden = true;
      li.appendChild(ul);
    } else {
      setTwistyLeaf(row);
    }
    return li;
  }

  async function loadChildren(row) {
    var childrenUl = getChildrenUl(row);
    if (!childrenUl || row.dataset.loaded === "true") return;
    var id = row.dataset.nodeId;
    var root = treeRootOf(row);
    if (!id || !root) return;
    var apiBase = root.dataset.treeApi;
    if (!apiBase) return;

    row.setAttribute("aria-busy", "true");
    try {
      var url = buildChildrenUrl(apiBase, id, root.dataset.asOf, root.dataset.dimension);
      var data;
      if (API && typeof API.request === "function") {
        var resp = await API.request(url);
        data = resp.data;
      } else {
        var r = await window.fetch(url);
        if (!r.ok) throw new Error("请求失败（状态码 " + r.status + "）");
        data = await r.json();
      }
      var children = (data && (data.children || data.results)) || [];
      if (!children.length) {
        row.dataset.hasChildren = "false";
        row.setAttribute("aria-expanded", "false");
        setTwistyLeaf(row);
        return;
      }
      var list = document.createElement("ul");
      list.className = "hr-org-tree__list";
      list.setAttribute("role", "group");
      children.forEach(function (n) {
        list.appendChild(buildNode(n, row));
      });
      childrenUl.appendChild(list);
      row.dataset.loaded = "true";
      row.setAttribute("aria-expanded", "true");
      childrenUl.hidden = false;
    } catch (e) {
      row.dataset.loadError = "1";
    } finally {
      row.removeAttribute("aria-busy");
    }
  }

  async function expandRow(root, row) {
    if (row.dataset.loaded === "false") {
      await loadChildren(row);
    }
    if (row.dataset.hasChildren !== "true") return;
    var childrenUl = getChildrenUl(row);
    if (childrenUl) {
      childrenUl.hidden = false;
      row.setAttribute("aria-expanded", "true");
    }
  }

  function collapse(row) {
    var childrenUl = getChildrenUl(row);
    if (!childrenUl) return;
    childrenUl.hidden = true;
    row.setAttribute("aria-expanded", "false");
  }

  function visibleItems(root) {
    return qsa(root, '.hr-org-tree__row[role="treeitem"]').filter(isVisible);
  }

  function focusRow(row, root) {
    qsa(root, '.hr-org-tree__row[role="treeitem"]').forEach(function (r) {
      r.setAttribute("tabindex", "-1");
    });
    row.setAttribute("tabindex", "0");
    row.focus();
  }

  var typeAheadBuffer = "";
  var typeAheadTimer = null;

  function typeAhead(root, current, key) {
    typeAheadBuffer += key.toLowerCase();
    window.clearTimeout(typeAheadTimer);
    typeAheadTimer = window.setTimeout(function () {
      typeAheadBuffer = "";
    }, 800);
    var items = visibleItems(root);
    var q = typeAheadBuffer;
    var from = current ? Math.max(0, items.indexOf(current)) : 0;
    var i, k, idx, it;
    for (i = 0; i < items.length; i++) {
      idx = (from + i) % items.length;
      it = items[idx];
      if ((it.dataset.search || "").indexOf(q) === 0) {
        focusRow(it, root);
        return;
      }
    }
    for (i = 0; i < items.length; i++) {
      idx = (from + i) % items.length;
      it = items[idx];
      if ((it.dataset.search || "").indexOf(q) !== -1) {
        focusRow(it, root);
        return;
      }
    }
  }

  function onKeydown(root, ev) {
    var target = ev.target && ev.target.closest
      ? ev.target.closest('.hr-org-tree__row[role="treeitem"]')
      : null;
    if (!target || !root.contains(target)) return;
    var items, i, next, firstChild, childrenUl, parent, pRow, url;

    switch (ev.key) {
      case "ArrowDown":
        ev.preventDefault();
        items = visibleItems(root);
        i = items.indexOf(target);
        next = items[Math.min(items.length - 1, i + 1)];
        if (next) focusRow(next, root);
        break;
      case "ArrowUp":
        ev.preventDefault();
        items = visibleItems(root);
        i = items.indexOf(target);
        next = items[Math.max(0, i - 1)];
        if (next) focusRow(next, root);
        break;
      case "ArrowRight":
        ev.preventDefault();
        if (target.dataset.hasChildren === "true") {
          if (target.getAttribute("aria-expanded") === "false") {
            expandRow(root, target);
          } else {
            childrenUl = getChildrenUl(target);
            firstChild = childrenUl
              ? childrenUl.querySelector('.hr-org-tree__row[role="treeitem"]')
              : null;
            if (firstChild) focusRow(firstChild, root);
          }
        }
        break;
      case "ArrowLeft":
        ev.preventDefault();
        childrenUl = getChildrenUl(target);
        if (childrenUl && target.getAttribute("aria-expanded") === "true") {
          collapse(target);
        } else {
          parent = target.closest(".hr-org-tree__children");
          if (parent && parent.parentElement) {
            pRow = parent.parentElement.querySelector(":scope > .hr-org-tree__row");
            if (pRow) focusRow(pRow, root);
          }
        }
        break;
      case "Home":
        ev.preventDefault();
        items = visibleItems(root);
        if (items[0]) focusRow(items[0], root);
        break;
      case "End":
        ev.preventDefault();
        items = visibleItems(root);
        if (items[items.length - 1]) focusRow(items[items.length - 1], root);
        break;
      case "Enter":
        url = target.dataset.nodeUrl;
        if (url && url !== "#" && url !== "") {
          window.location.href = url;
        } else if (target.dataset.hasChildren === "true") {
          ev.preventDefault();
          if (target.getAttribute("aria-expanded") === "false") {
            expandRow(root, target);
          } else {
            collapse(target);
          }
        }
        break;
      default:
        if (ev.key && ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
          ev.preventDefault();
          typeAhead(root, target, ev.key);
        }
    }
  }

  function applySearch(root, q, statusEl) {
    var all = qsa(root, '.hr-org-tree__row[role="treeitem"]');
    var matches = [];

    all.forEach(function (row) {
      row.classList.remove("is-search-match");
    });

    if (!q) {
      qsa(root, ".hr-org-tree__item").forEach(function (li) {
        li.hidden = false;
      });
      qsa(root, ".hr-org-tree__children").forEach(function (ul) {
        ul.hidden = false;
      });
      if (statusEl) statusEl.textContent = "";
      return;
    }

    var count = 0;
    var firstMatch = null;
    all.forEach(function (row) {
      if ((row.dataset.search || "").indexOf(q) !== -1) {
        row.classList.add("is-search-match");
        matches.push(row);
        count += 1;
        if (!firstMatch) firstMatch = row;
      }
    });

    // 展开包含匹配节点的祖先行（已渲染的直接展开；未加载的在点击时才懒加载）
    all.forEach(function (row) {
      if (matches.indexOf(row) !== -1) return;
      if (row.querySelector(".hr-org-tree__row.is-search-match")) {
        if (row.dataset.hasChildren === "true") {
          row.setAttribute("aria-expanded", "true");
          var ul = getChildrenUl(row);
          if (ul) ul.hidden = false;
        }
        matches.push(row);
      }
    });

    all.forEach(function (row) {
      var item = row.closest(".hr-org-tree__item");
      var keep = matches.indexOf(row) !== -1;
      if (item) item.hidden = !keep;
      if (!keep) {
        row.setAttribute("aria-expanded", "false");
        var ul = getChildrenUl(row);
        if (ul) ul.hidden = true;
      }
    });

    if (statusEl) {
      statusEl.textContent = count ? count + "\u4E2A\u5339\u914D" : ""; // N 个匹配
    }
    if (firstMatch) firstMatch.scrollIntoView({ block: "nearest" });
  }

  function initSearch(root, input, statusEl) {
    input.addEventListener("input", function () {
      applySearch(root, input.value.trim().toLowerCase(), statusEl);
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        input.value = "";
        applySearch(root, "", statusEl);
        input.blur();
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        var match = root.querySelector(".hr-org-tree__row.is-search-match");
        if (match) focusRow(match, root);
      }
    });
  }

  function init(root) {
    if (!root || root.dataset.hrInited) return;
    root.dataset.hrInited = "1";

    var all = qsa(root, '.hr-org-tree__row[role="treeitem"]');

    // roving tabindex：默认只保留一个可 Tab 焦点（选中节点优先，否则首个）
    var focusTarget = null;
    var selectedId = root.dataset.selectedId;
    if (selectedId) {
      all.forEach(function (row) {
        if (row.dataset.nodeId === selectedId) {
          row.classList.add("is-selected");
          row.setAttribute("aria-selected", "true");
          row.setAttribute("aria-current", "true");
          focusTarget = row;
        }
      });
    }
    all.forEach(function (row) {
      row.setAttribute("tabindex", row === focusTarget || (!focusTarget && row === all[0]) ? "0" : "-1");
    });
    if (focusTarget) {
      focusTarget.scrollIntoView({ block: "nearest" });
    }

    var searchInput = root.querySelector(".hr-org-tree__search");
    var statusEl = root.querySelector("#" + (root.id || "hr-org-tree") + "-search-status");
    if (searchInput) initSearch(root, searchInput, statusEl);

    root.addEventListener("click", function (ev) {
      var row = ev.target.closest
        ? ev.target.closest('.hr-org-tree__row[role="treeitem"]')
        : null;
      if (!row) return;
      if (ev.target.closest("a.hr-org-tree__label")) return;
      if (row.dataset.hasChildren === "true") {
        ev.preventDefault();
        if (row.getAttribute("aria-expanded") === "false") {
          expandRow(root, row);
        } else {
          collapse(row);
        }
      }
    });

    root.addEventListener("keydown", function (ev) {
      onKeydown(root, ev);
    });
  }

  function initAll() {
    qsa(document, "[data-hr-org-tree]").forEach(init);
  }

  window.HrOrgTree = { init: init, initAll: initAll };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})(window, document);
