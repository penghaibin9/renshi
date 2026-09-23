# V16 前端仓库清洗边界

## 结论

V16 的 HR01～HR18 已从 Horilla 克隆前端的 `index.html` 中解耦。当前人事业务页面统一继承 `frontend/templates/hr/base.html`，旧 Horilla 主题壳只作为非人事兼容/支持页面保留，不再是人事业务页面的运行时父模板。

## 当前唯一的人事前端入口

- 业务父模板：`frontend/templates/hr/base.html`
- 左侧导航：`frontend/templates/hr/components/module_sidebar.html`
- 顶部：`frontend/templates/hr/components/header_clean_v16.html`
- V16 视觉：`frontend/static/hr/css/hr-ui-a-v16.css`
- 仓库清洗壳：`frontend/static/hr/css/hr-shell-clean-v16.css`
- 页面查找：`frontend/static/hr/js/core/hr-ui-a-v16.js`
- 移动侧栏：`frontend/static/hr/js/core/hr-shell-clean-v16.js`
- 中文防回退：`backend/horilla/canonical_hr_language.py`

当前纳入边界的 HR 模板共 **175** 个；直接继承旧 `index.html` 的 HR 模板已经从 55 个降为 **0**。

## 为什么不直接删除全部 Horilla 老代码

旧仓库里仍有 employee / attendance / leave / payroll / pms / asset / helpdesk 等上游应用。V16 的部分数据模型、兼容数据和后台服务仍可能依赖这些 Python app；直接删目录会把“清前端”变成“重写后端”，风险不可控。因此本轮采取 **运行时隔离 + 路由适配 + 源码显式标记 + 自动门禁**，而不是按文件名大批删除。

## 已封住的常见英文跳转来源

1. HR 页面不再加载旧 header、旧 profile 菜单、旧 language switcher、旧 attendance 打卡区和旧 floating actions。
2. `/settings/` 根入口先落到中文系统管理中心；`/notifications/` 转到 `/hr/todos`。
3. HR、公开招聘、settings 支持页强制 `zh-hans`，旧语言 cookie 不再覆盖这些入口。
4. 系统管理中心本身改用 `hr/base.html`，人员/组织/岗位三个高频卡片直接进入 HR03/HR02 的中文正式页面。
5. 新增源码门禁，未来有人再让 HR 模板 `extends "index.html"` 会直接测试失败。

## 保留但隔离的区域

- `backend/horilla_theme/templates/index.html`：非 HR 上游兼容壳。
- `frontend/templates/index.html`：历史 fallback 快照，不允许 HR 继承。
- 非 HR 上游 app 的 templates/static：暂不物理删除，待证明没有 Python/迁移/管理功能依赖后再分批归档。
- settings 内仍有少量没有 HR 等价页的底层配置（角色权限、邮件、安全审计等），继续保留能力，但语言已固定为中文；后续可以单独做“系统管理全量国产化/去 Horilla 模板”施工。
