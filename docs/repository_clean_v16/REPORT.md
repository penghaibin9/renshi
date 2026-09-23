# Yueke University HR V16 Repository Clean Report

## 结论

本轮确认用户“后台偶发跳回英文旧页面”的主根因不是 HR01～HR18 业务路由缺失，而是 **55 个当前 HR 模板仍直接继承 Horilla 克隆前端的 `index.html`**。该旧 shell 会继续装载 Horilla 的 header、profile 菜单、语言切换、考勤快捷区、floating actions 及旧 settings/notifications 等入口，因此即使 V16 最后一层 CSS 已经美化，页面仍有机会从业务链逃逸回上游旧前端。

本轮已把 V16 改成 **“业务代码保留、旧前端运行时隔离”** 的结构：HR01～HR18 使用独立 `hr/base.html`；旧 Horilla shell 只保留给尚未迁移的非 HR 支持页，不再作为人事业务页父模板。

## 已施工

1. 新建 `frontend/templates/hr/base.html`，作为 HR01～HR18 唯一业务 shell。
2. 新建 `header_clean_v16.html`、`hr-shell-clean-v16.css/js`，只保留人事导航、页面搜索、待办、本人服务、系统管理和退出。
3. 55 个 HR 直接模板由 `extends "index.html"` 改为 `extends "hr/base.html"`；间接继承链继续沿用模块内部 base。
4. HR shell 不再 include：旧 header、旧 profile menu、language switcher、attendance in/out、floating buttons、company switcher。
5. 新增 `CanonicalHrLanguageMiddleware`：`/hr/`、`/recruit/`、`/settings/` 与 `/login/` 固定 `zh-hans`，旧语言 cookie 不再把这些页面切回英文。
6. `/settings/` 根入口前置重定向到中文“系统管理中心”；`/notifications/` 转到 `/hr/todos`。
7. 系统管理中心自身改用 `hr/base.html`；“账号与人员 / 组织与部门 / 岗位与职务”三个高频入口直接进入 HR03 / HR02 正式中文页。
8. 对旧 Horilla shell 添加源码隔离标记，明确禁止 HR 再继承。
9. 新增 `scripts/audit_hr_frontend_boundary.py` 和静态门禁测试；未来再次出现 HR 模板继承旧 `index.html` 会直接失败。
10. 删除交付目录中的 `__pycache__`、`.pyc`、`.pytest_cache`，不把运行缓存继续装进源码包。

## 为什么没有暴力删除 employee / attendance / leave / payroll / pms 等目录

这些目录虽然含旧 UI，但也可能仍承担模型、迁移、权限、兼容 service 或数据关系。直接按“英文模板多”删除会把一次前端清洗变成后端重构，并可能破坏 V15/V16 已验收的业务事实。因此本轮采用：

**旧浏览器入口重定向 + HR shell 解耦 + 后端兼容 app 保留 + 清晰隔离清单 + 自动门禁。**

等后续拿到“无 import / 无 FK / 无 migration / 无 service 调用”的证据，再分 app 做物理归档。

## 校验结果

- canonical HR 模板：清洗前 173 个；清洗后因新增 base/header 为 175 个。
- HR 模板直接继承旧 `index.html`：**55 → 0**。
- canonical HR 引用旧 floating/language/profile/attendance shell 组件：**0**。
- canonical HR 硬编码跳往旧 employee/attendance/leave/payroll/pms/... 浏览器根：**0**。
- migrations：**520 个文件，新增 0、删除 0、内容变化 0**。
- 新增/更新的仓库边界测试：**12 passed**。
- 新增 JS 与 V16 JS：`node --check` 通过。
- 新增 Python middleware / 路由：`py_compile` 通过。
- `python scripts/audit_hr_frontend_boundary.py`：`pass=true`。

完整 `pytest tests` 在当前施工容器未完成，因为容器没有安装 Django，且完整测试收集还要求 `backend` 加入 Python 路径；这是执行环境依赖缺失，不记录为产品绿色，也不冒充全量回归通过。

## 仍保留的边界

底层 settings 中“角色权限、邮件、安全审计”等少量能力目前没有 HR01～HR18 的一一对应页，所以功能代码仍保留上游 settings 模板。它们已被固定为简体中文入口，且系统管理首页已换 clean shell，但 **还没有做全量 settings 页面视觉重写**。如果继续做下一轮，建议只处理这一块，不再动 18 个业务模块。

## 版本语义

这是 **V16 Repository Clean maintenance derivative**，不是新增 HR19/HR20，也不是重写业务版 V17。数据库迁移和业务事实保持 V16。
