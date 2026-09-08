# HR03 教职工主档

这是 HR03 的模块入口。HR03 是人员身份、任职状态、基础档案和关键历史事实的权威来源。

## 小白先看这里

- `models/`：人员主档及历史事实。
- `services/`：正式写操作和状态转换。
- `selectors/`：人员查询、历史查询、列表筛选。
- `api/`：正式 API。
- `policies/`：业务规则与权限策略。
- `legacy/`：仍需兼容的旧逻辑，禁止新增正式能力。
- `templates/` / `views/`：人员管理页面。
- `tests/`：主档、权限、租户隔离与历史事实测试。

## 重构硬规则

1. 人员主档不能被招聘、合同、考勤等模块直接改表。
2. 历史事实不能因今天修改而污染过去记录。
3. tenant / permission / audit 默认 fail-closed。
4. 旧代码能复用则迁入清晰目录；无引用、无业务价值且与设计冲突的再删除。
5. 正式 API 统一 `/api/v1/hr/...`。

## 教职工账号邀请与 HR17 本人服务

正式账号不能由导入人员时自动生成，也不能把初始密码写入 Excel、日志或审计。账号开通链为：

`HR03 已有主档 → 已核验当前邮箱 → 管理员签发一次性邀请 → 本人设置登录账号与密码 → CompanyGroupAssignment(仅 hr.self.view) → HrAccountLink(ACTIVE) → HR17 SELF`

硬边界：

- 管理端签发需要语义权限 `hr.staff.account.manage`，并继续受当前学校与 HR03 data scope 约束。
- 邀请邮箱只读取 HR03 `HrPersonContact` 中已核验且当前有效的工作/个人邮箱；API 不接受收件邮箱覆盖。
- 邀请 bearer 使用高熵随机值，数据库只保存带 namespace 的 SHA-256 摘要；摘要本身不能作为 bearer 重放。
- HTTP path/query 只携带非 secret 的 invitation UUID；bearer 仅放在 URL `#fragment`。浏览器 fragment 不会发送给 Nginx/反向代理，激活页外部脚本会把 secret 移入 POST body，并立即从地址栏/history 清除。
- 同一 staff 重新签发会撤销此前所有未消费邀请；过期、撤销、已使用 token 均 fail-closed。
- 任意既有 `HrAccountLink`（包括 SUSPENDED / UNLINKED）都会阻止重新开账号，避免静默替换历史关联。
- 接受邀请时用户、学校 SELF 角色、`CompanyGroupAssignment`、`HrAccountLink`、邀请消费与业务审计在一个事务中完成。
- 系统保留组 `__system_hr17_self__` 只允许 `hr.self.view`。如果组被人工污染出额外权限，激活直接拒绝而不是扩大权限。
- 激活 GET 不读取 secret，也不回显姓名、工号或邮箱；POST 使用真实 CSRF、`Cache-Control: no-store` 和 `Referrer-Policy: no-referrer`。
- 激活页面不自动登录；用户必须用刚设置的密码重新登录，邀请 possession 不升级成长期会话。
- 当前没有仓库级正式邮件发送 Authority，因此签发 API 明确返回 `deliveryMode=MANUAL_LINK`；不得把“生成邀请链接”描述成“邮件已发送”。

正式管理 API：

- `POST /api/v1/hr/staff/{staff_id}/account-invitations`
- `POST /api/v1/hr/account-invitations/{invitation_id}/revoke`

签发响应中的完整邀请 URL 只出现一次，响应为 `no-store`；运维层不得记录响应体。

## 激活页校验恢复与缓存回归（PR #53）

对应 HRP-03 / HRP-06 / HRP-08 / HRP-12；调用链：
`invitation_activate.html → account_invitation.js → 同一 activate-account POST → AccountInvitationService.accept → 原账号/学校SELF成员/HrAccountLink/审计事务`。

账号或密码校验不通过时，通过同一POST的 `Accept: application/json` 返回字段错误，
页面不跳走，教师可修改后明确再次提交。普通表单的HTML/302行为继续兼容。
JSON协商不是鉴权，CSRF照常检查；不新增注册路由、不改人员、权限、迁移或原事务服务。
成功JSON只返回固定完成页地址，避免fetch提前消费一次性完成页；之后仍需显式登录。

邀请密钥仅在当前页面内存及必要POST body中，不保存到localStorage/sessionStorage、Cookie、
history state或错误HTML；页面离开/成功/终止时清除。修改失败不要求重新签发邀请。
处理中禁重交；结果未知、网络中断或超时不自动重放账号写入，也不声称服务端已回滚。
UI明确提示先核对登录结果；需继续时重开原邀请链接，服务端仍拒绝已使用邀请。

缓存测试按指令核验 `no-store / no-cache / must-revalidate / private / max-age=0`，
而非将整个头部固定成单个字符串；不移除Django never_cache附加的更严格保护。
同时覆盖激活GET、失败400、成功响应、完成页及JSON的CSRF/UUID/撤销/已登录拒绝。

验收分开记账：

```bash
python manage.py test hr_staff.tests.test_account_invitation --keepdb --noinput
python tests/visual/hr_account_activation_ui_tests.py -v
HR_VISUAL_AUDIT=1 python manage.py test tests.visual.hr_account_activation_browser_tests.AccountActivationBrowserTests --keepdb --noinput
```

UI专项使用真实Chromium DOM，但显式隔离location/history/HTTP，不算真实站点导航；
真实专项使用Django/MySQL服务、一次性邀请、弱密码400后同页修正、显式登录HR17及数据库回读，
桌面与手机分别执行，不替换HTTP、不注入登录Cookie。合成人员和服务签发邀请仅为前置条件，
不声称学校管理员的签发/复制UI也由此验收。最终PASS只以对应提交实际运行结果为准。
xlsx导入导出、外发邮件与全生命周期验收不在该页面切片中，不计为通过。

### 浏览器中途事实回读的线程边界

Playwright 同步接口仍有活动事件循环；同步 ORM 和数据库会话读取必须在独立线程中
完成，不能关闭 Django 的异步安全保护。测试只传入学校、人员、邀请等标量标识；
工作线程独立取得连接、完成查询并关闭连接，只返回布尔值与计数，不返回模型或会话。
弱密码被拒绝后的无账号、无本人绑定、无邀请消费和无成功审计，在再次提交前核验；
完成页之后、显式登录之前核验未自动登录、未持久化邀请密钥、完成标记已消费。
最终账号权限、本人关联和审计回读仍在浏览器上下文退出后执行，原业务路径不跳过。
