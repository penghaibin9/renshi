# 系统设置运行证据台账

本台账只记录由真实浏览器和真实 MySQL 产生的证据。未通过的项目保持 `PENDING`，不得根据页面截图主观改为完成。

| 验收项 | 自动化入口 | 证据文件 | 当前状态 |
|---|---|---|---|
| 生产登录 | `scripts/system_settings_browser.py` | `00-admin-landing.png`、管理员 Trace | PENDING |
| 右上角菜单 | 同上 | 菜单诊断、设置入口元数据 | PENDING |
| 设置首页 | 同上 | `01-settings-home.png` | PENDING |
| 设置子页面 | 同上 | `settings-*.png`、导航清单 | PENDING |
| 保存并刷新回读 | 同上 | `02-setting-persisted.png`、`evidence.json` | PENDING |
| MySQL 落库 | `.github/workflows/system-settings-browser.yml` | `mysql-seal.json` | PENDING |
| 普通角色边界 | 同上 | `03-business-user-boundary.png`、普通角色 Trace | PENDING |
| URL 与非占位入口 | `base.test_system_settings_surface_contract` | 测试日志 | PENDING |
| 精确 SHA 封板 | PR #53 | 同一 SHA 的全部检查 | PENDING |

## 回填规则

1. 只允许把 GitHub Actions 已完成且结论为成功的项改为 `PASS`。
2. 必须同时记录精确 SHA、Workflow Run ID、执行时间和证据 Artifact 名称。
3. 任一后续提交触及公共导航、权限、设置表单、URLConf 或数据库模型时，相关项目重新变为 `PENDING`。
4. 不保留账号口令、Token、密钥或生产学校敏感数据。
