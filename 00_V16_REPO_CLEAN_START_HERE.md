# 跃科高校人事 V16｜仓库清洗版入口

这一包以 `Yueke_University_HR_UIA_Integration_V16_20260920` 为唯一来源，只做前端仓库边界清洗，不重写人事业务。

## 这次解决什么

- HR01～HR18 不再继承 Horilla 克隆前端的 `index.html`。
- 人事业务统一进入 `frontend/templates/hr/base.html`。
- 旧 header / profile / language switcher / attendance 快捷区 / floating actions 不再进入人事页面。
- `/settings/` 根入口改到中文系统管理中心，`/notifications/` 改到人事待办。
- HR、公开招聘、settings 支持页固定简体中文，避免旧语言 cookie 把页面切回英文。
- 系统管理中心本身也改用人事 clean shell；人员、组织、岗位高频入口直接回到 HR03/HR02。
- 已删除仓库缓存文件，但没有删除 migrations、业务模型、权限、审计、HR15 薪酬代码。

## 为什么旧 Horilla Python app 还在

employee / attendance / leave / payroll / pms 等目录可能仍被数据模型、迁移、服务或兼容接口引用。本轮把它们定义为“后端兼容区”，不再作为 HR 的用户前端入口；没有依赖证据前不做暴力删除。

## 自动门禁

运行：

```bash
python scripts/audit_hr_frontend_boundary.py
python -m pytest -q tests/test_hr_frontend_clean_boundary.py tests/test_hr_ui_v16_contract.py
```

详细边界和遗留清单见 `docs/repository_clean_v16/`。
