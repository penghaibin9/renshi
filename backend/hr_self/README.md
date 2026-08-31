# HR17 教职工服务

> 设计事实源：`docs/17_HR17_教职工服务_施工总册_终极版.md`

## 这个模块负责什么

HR17 是教职工 SELF 体验与服务入口 Authority：聚合本人状态、待办、服务目录、办理进度、工资条/合同/证明等本人文件，并把真实写操作路由到 HR03–HR16 对应业务 Authority。

## 不负责什么

- 不复制 Staff、Contract、Assessment、Title、Appointment、Payroll、Exit 等正式业务表。
- 不自建请假、职称、聘任、离职等第二套状态机。
- 本人可见不等于本人可任意修改正式事实。

## 固定技术合同

- API：`/api/v1/hr/self`
- Permission：`hr.self.*`
- 数据库：MySQL-only
- SELF 身份必须由登录态 + tenant + staff resolver 得出，前端传 staff_id/tenant_id 不能作为授权依据。
- 所有本人文件下载、搜索、待办和申请必须使用相同 Scope。

## 小白看代码顺序

1. `providers/`：从 HR03–HR16 读取本人事实。
2. `services/`：统一服务目录、发起入口、补正/撤回路由。
3. `selectors/`：首页 Bootstrap、我的状态、待办、文件和进度。
4. `api/`：统一 `/api/v1/hr/self`。
5. `templates/` / 移动端入口：教职工高频体验。
6. `tests/`：SELF 身份、IDOR、跨学校、文件安全、性能和视觉验收。
