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

## 首次激活与首页独立加载（PR #53）

本切片对应 HRP-03 / HRP-06 / HRP-08 / HRP-12：学校邀请激活 → 显式密码登录 → 本人主档与服务入口可用。

`workspace.html → hr17-self.js → 既有 SELF bootstrap / self_records → SelfIdentityService 与原来源服务`。
不改登录、SELF 权限、后端路由、身份解析或正式事实，不新增数据库表或写操作。

- 首页、服务大厅、待办、进度只消费既有 bootstrap，不额外调用工资/合同/材料汇总。
- 工资、合同、文件页并行读取所需记录，但主档、指标和来源状态不再等待记录请求结束。
- 记录读取中、成功空结果、失败暂不可用是三个状态。失败不能伪装成“您没有记录”；
  先到的记录等待本人汇总完成再显示，后到的记录不能覆盖本人汇总的失败提示。
- 超时和同源请求策略保持原值；原服务搜索、常用设置、来源降级显示保持不变。

账号中文校验专项使用真实 HR03 主档、已核验合成邮箱和服务签发的一次性邀请，
通过启用 CSRF 检查的 Django Client 请求原页面。不替换 inspect/accept/用户名或密码校验，
不为测试补造服务方法。动态密码长度、中文反馈、语言恢复及拒绝后无账号/成员/绑定/消费/成功审计一起核验。
合成主档和签发是该测试的前置，不代表管理员签发 UI 或外发邮件已验收。

```bash
python tests/visual/hr17_self_loading_tests.py -v
python manage.py test hr_staff.tests.test_account_activation_language --keepdb --noinput --verbosity 2
HR_VISUAL_AUDIT=1 python manage.py test tests.visual.hr_account_activation_browser_tests.AccountActivationBrowserTests tests.visual.hr17_visual_audit_tests.Hr17VisualAuditTests --keepdb --noinput --verbosity 2
```

第一条使用 Chromium DOM 与隔离请求，仅证明前端加载/错误呈现；不能替代后两条的真实
Django/MySQL/浏览器证据。视觉工作流保留原门禁，并单独执行前两项回归；语言日志随原激活早期工件保存。
每次通过只属于其产品 SHA 和测试 checkout SHA；未完成检查不能沿用旧绿色。xlsx、真实邮件及全站逐页美化不在本次切片，不计通过。
