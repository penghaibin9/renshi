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
- 同一 staff 重新签发会撤销此前所有未消费邀请；过期、撤销、已使用 token 均 fail-closed。
- 任意既有 `HrAccountLink`（包括 SUSPENDED / UNLINKED）都会阻止重新开账号，避免静默替换历史关联。
- 接受邀请时用户、学校 SELF 角色、`CompanyGroupAssignment`、`HrAccountLink`、邀请消费与业务审计在一个事务中完成。
- 系统保留组 `__system_hr17_self__` 只允许 `hr.self.view`。如果组被人工污染出额外权限，激活直接拒绝而不是扩大权限。
- 激活页面不自动登录；用户必须用刚设置的密码重新登录，邀请 possession 不升级成长期会话。
- 当前没有仓库级正式邮件发送 Authority，因此签发 API 明确返回 `deliveryMode=MANUAL_LINK`；不得把“生成邀请链接”描述成“邮件已发送”。

正式管理 API：

- `POST /api/v1/hr/staff/{staff_id}/account-invitations`
- `POST /api/v1/hr/account-invitations/{invitation_id}/revoke`

公开激活入口由签发响应生成，激活页使用真实 CSRF、`Cache-Control: no-store` 和 `Referrer-Policy: no-referrer`。
