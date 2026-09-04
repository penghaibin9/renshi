# 17_HR17_教职工服务_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API（`/api/v1/hr`）、数据库目标（MySQL-only）、事件、权限、Legacy、审计、安全和最终生产 Gate。
> PATCH-08/10 补充：HR17-05 提供奖励/处分通知与复核/申诉入口（Experience only）；HR17-04 展示职业年金/福利 Statement（SELF）。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR17 教职工服务中心  
> 对外菜单名称：教职工服务  
> 三级模块数量：6  
> 总体策略：REWRITE（接管 Horilla Employee Self-Service / My Dashboard / Requests 等入口与体验；保留可复用的登录态、个人入口、Request/通知/部分移动能力；重建“统一我的服务门户 + SELF Provider 聚合 + 业务跳转/发起 + 文件/证明 + 退休服务”的高校 ESS；绝不重建 HR03–HR16 业务 Authority）  
> 版本：V1.0 终极冻结版  
> 文档性质：HR17 唯一权威施工事实源；可直接整份交给编码 AI 执行“现有 ESS/Employee Dashboard 基线复审 → SELF 身份解析 → 服务目录 → 首页 Bootstrap → 我的档案与更正 → 我的任职/合同/资格/发展/考核/职称/聘任 → 我的考勤休假/薪酬福利/工资条/证明文件 → 统一申请发起与进度 → 消息待办/帮助 → 关怀与退休后服务 → 移动端高频 → Legacy ESS 兼容 → 安全/性能/E2E/Accessibility/Visual Regression → ESS Authority of Experience 切换”的生产级施工。  
> 适配底座：Horilla HRMS 2.0（当前 `penghaibin9/renshi` 基线；S0 必须以目标分支真实代码再次核验）  
> 前置标准：继承《01_HR01》至《16_HR16》终极版的 A0 多学校 fail-closed、API 版本化、统一错误信封、公共 UI、权限/数据范围、文件安全、敏感字段、异步任务、审计、可观测性、Excel、幂等、事务、Outbox、规则/模板版本冻结、Legacy 退出和 AI 施工纪律。  
> 强依赖：HR03 提供本人主档/任职/联系方式/材料/更正 Authority；HR07 提供本人合同；HR09 提供教师资格/双师型；HR10 提供培训/企业实践/教师发展；HR11 提供本人考勤、休假、加班及申请入口；HR12 提供本人考核结果/确认/申诉入口；HR13 提供职称申报/结果；HR14 提供岗位聘任申报/结果/当前聘任；HR15 提供本人薪酬档案、工资条、社保公积金、支付状态及相关服务；HR16 提供辞职/退休申请进度、离校任务、退休事实；HR05/HR06/HR08 等通过服务目录按本人可办理范围暴露；HR01 管理工作台与 HR18 数据中心不向普通教职工复用管理视图。  
> 编写日期：2026-08-08  
> 核心原则：**HR17 是“体验与自助服务 Authority”，不是“人事事实 Authority”。首页聚合 ≠ 复制数据；我的档案 ≠ 自由修改正式事实；发起申请 ≠ HR17 自建状态机；查看合同/工资条/考核/职称 ≠ HR17 复制业务表；SELF 身份必须从登录态解析；一个入口必须能告诉教职工“我是谁、我现在有什么状态、我该办什么、我能办什么、我已经办到哪一步、我的正式文件在哪里”。**
# 0. 六个三级模块冻结

```text
HR17 教职工服务中心
├─ HR17-01 我的服务首页
├─ HR17-02 我的档案与更正
├─ HR17-03 我的任职与成长
├─ HR17-04 我的薪酬权益与文件
├─ HR17-05 我的申请与办理
└─ HR17-06 关怀与退休服务
```

职责严格分离：

- **HR17-01 我的服务首页**：本人状态、关键提醒、待办、最近办理、常用服务、消息、服务搜索、移动端首页。
- **HR17-02 我的档案与更正**：个人基础资料、联系方式、家庭/紧急联系人等授权资料、任职快照、材料、信息完整度、可自助修改字段、正式更正申请。
- **HR17-03 我的任职与成长**：当前岗位/任职、合同、教师资格/双师型、培训/企业实践、年度/聘期考核、职称、岗位聘任、职业发展时间线。
- **HR17-04 我的薪酬权益与文件**：工资条、薪酬摘要、社保公积金个人侧、支付状态、个税最小展示、合同/证明/人事文件/电子文件下载与验证。
- **HR17-05 我的申请与办理**：统一服务目录、休假/加班/更正/培训/考核确认/职称/竞聘/辞职/退休等业务发起入口、进度、补正、撤回、待我操作。
- **HR17-06 关怀与退休服务**：生日/入职周年等可选关怀、通知活动、退休预审提示、退休后服务入口、证明/工资条历史、返聘 referral、服务咨询。

# 1. 结论先行

HR17 不是把 HR03–HR16 的菜单复制一遍，也不是一个“个人信息页面”。

真正成熟的 ESS 应形成：

```text
                Identity / Tenant / Staff Resolver
                            │
                            ▼
                   Self-Service Gateway
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        Self Read        Self Action     Self Documents
             │              │              │
             ├──────────────┼──────────────┤
             ▼              ▼              ▼
          HR03/07         HR11/12/13      HR07/15/16
          HR09/10         HR14/16...      Documents...
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    HR17 Bootstrap View
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
      我的状态          我的待办/办理        我的文件/权益
          │                 │                  │
          └─────────────────┼──────────────────┘
                            ▼
                PC / Mobile / WeChat-compatible
```

HR17 必须做到：
1. 教职工登录 10 秒内知道“有没有事要我处理”；
2. 不需要知道 HR03/HR07/HR15 这些后台模块编号；
3. 不需要在人事系统里到处找“工资条在哪里”“合同在哪里”“请假在哪里”；
4. 一个服务搜索能搜到“改手机号、开证明、看工资、申请退休”等真实服务；
5. 每个办理都能看到真实状态和下一步；
6. 每份文件都有来源、版本、时间和访问权限；
7. 个人信息修改按字段风险选择“直接改 / 验证后改 / 发更正申请”；
8. 移动端优先覆盖高频任务；
9. 退休后仍可按独立权限查看被允许保留的服务；
10. 任何 HR17 显示值都能追到业务 Authority，而不是另存一份。

# 2. 生产级红线

- 不得把 HR17 做成 HR01 管理看板换个标题。
- 不得普通教职工首页展示全校人数、性别结构、部门人数、全员最近入职等管理指标。
- 不得把 Horilla `employee_dashboard` 当前全员统计直接当 ESS 首页。
- 不得把 Employee 管理列表、Configuration 放进普通教职工服务主导航。
- 不得把 HR03–HR16 二级菜单完整复制到 HR17。
- 不得让教职工理解后台领域编号才能办事。
- 不得 HR17 自建合同、工资、考核、职称、岗位聘任、离校第二套状态机。
- 不得 HR17 保存一份独立 staff master 真值。
- 不得 `GET /self/...` 接受任意 staff_id。
- 不得前端隐藏 staff_id 但后端仍允许通过 query/body 指定他人。
- 不得从 URL 中的 employee id 推断 SELF。
- 不得一个人多 EmploymentRelationship 时默认 `.first()`。
- 不得本人可以直接修改工号、入职日期、人员类别、正式学历、正式职称、岗位等级等权威字段。
- 不得所有个人信息都走审批，手机号等允许自助字段应支持合理验证后直接变更。
- 不得银行卡号在 HR17 普通页面明文展示。
- 不得身份证号、税号、社保账号完整展示。
- 不得工资条通过永久公开 URL 下载。
- 不得合同扫描件通过 `/media/...` 裸链接。
- 不得工资条下载接口仅验证登录而不验证本人。
- 不得考核私密评委意见暴露给本人，除非该字段按 HR12 明确可见。
- 不得 360 匿名反馈破坏匿名规则。
- 不得 HR17 自己重算工资、个税、社保公积金。
- 不得 HR17 自己重算退休日期。
- 不得 HR17 把 HR16 forecast 当正式退休批准。
- 不得 HR17 把 HR14 proposed 当正式岗位聘任。
- 不得 HR17 把 HR13 application 通过当正式职称结果。
- 不得 HR17 把 HR12 calculated score 当 final grade。
- 不得 HR17 把 HR07 signed waiting effective 显示成 ACTIVE 合同。
- 不得 Provider `UNAVAILABLE` 时显示空白并让用户以为“没有数据”。
- 不得 Provider `STALE` 时无提示展示旧工资/旧岗位。
- 不得在首页串行请求十几个小接口形成 waterfall。
- 不得首屏 20 个彩色快捷卡。
- 不得移动端照搬 PC 大表格。
- 不得关键操作只有 hover。
- 不得所有服务都用右侧抽屉。
- 不得把复杂职称/竞聘/退休表单塞进通用 Quick Action。
- 不得搜索只搜菜单名而搜不到“我想开收入证明”这种意图。
- 不得搜索结果跳到不存在/无权限页面。
- 不得通知和待办重复无限生成。
- 不得“已读”状态覆盖业务状态。
- 不得 HR17 消息删除业务 Authority 的待办。
- 不得撤回按钮由 HR17 猜测状态，必须由 source action contract 返回。
- 不得 HR17 自动批准任何人事申请。
- 不得 HR17 代替 source module 处理 RETURNED/REJECTED。
- 不得用本地 mock 数据让首页看起来有工资/合同。
- 不得一个失败 source 导致整个首页 500。
- 不得一个 source 失败时静默用 legacy 值。
- 不得跨租户 identity resolver。
- 不得平台 SaaS 运维使用“模拟员工”功能无审计查看工资合同。
- 不得管理员 impersonation 默认启用。
- 不得生日关怀暴露完整出生日期给无关人员。
- 不得把家庭成员、专项附加扣除等敏感信息做成文化关怀数据源。
- 不得退休人员保留原在职权限。
- 不得返聘后把退休前 relationship 当 current relationship。
- 不得 HR17 修改 HR16 RetirementFact。
- 不得导出“我的全部档案”时无敏感字段二次确认。
- 不得电子证明生成成功但没有 version/hash/source。
- 不得证明二维码验证泄露工资、身份证或敏感离职原因。
- 不得 AI 回答工资/合同/退休问题时编造不存在的个人事实。
- 不得 AI 直接执行敏感修改或人事提交而无明确确认。
- 不得为过测试关闭 SELF/403 校验。
- 不得只跑 desktop 不跑移动端。
- 不得施工阶段直接合并 main 或部署生产。

# 3. ESS 产品定位

HR17 是 Employee Self-Service + Employee Experience Layer：

```text
Read my authoritative facts
Start my allowed transactions
Complete my assigned actions
Get my official documents
Understand my status
Find help
```

不是：
```text
Manage all employees
Configure HR policies
Approve everyone
Run school-wide reports
```

# 4. SAP Employee Central 1H 2026 对标

成熟 ESS 支持员工在权限控制下更新本人个人信息，并通过 Quick Actions 提供简化、角色相关的高频操作。
对跃科的启发：
- 服务权限模板化；
- Quick Action 字段最小化；
- 复杂业务跳正式详情页；
- SELF 与管理端明确分开；
- error/warning 可理解。

# 5. Workday ESS 对标

成熟员工体验强调：
- HR 与工资信息单入口；
- payslip；
- compensation/benefits；
- case/help；
- mobile；
- everyday tasks。

跃科要吸收“一个入口、移动优先、高频服务直达”，不复制其商业模块结构。

# 6. 个人信息保护法基线

HR17 是个人信息高密度入口，必须把个人信息保护当核心架构：
- 最小必要；
- 明确目的；
- 敏感个人信息加强保护；
- 本人查阅/复制/更正等权利；
- 权限和日志；
- retention；
- 第三方 Provider 最小传输。

“本人可见”不代表可以在任何页面无限聚合所有敏感信息。

# 7. 电子文件基线

电子合同、证明、工资条等文件需要：
- 可调取；
- 完整性；
- 版本；
- hash；
- 来源；
- 签名/盖章 Provider（如适用）；
- 下载审计。

HR17 只做本人安全访问入口，正式文书 Authority 仍在 HR07/15/16/Document Provider。

# 8. Horilla 当前 ESS 可复用能力

当前仓库 `employee/sidebar.py` 已有：
- My Dashboard；
- Requests；
- Work Schedules；
- Employee 登录态；
- accessibility helper；
- employee relation。

可作为 Legacy 入口和部分组件来源。

# 9. Horilla 当前侧栏问题

当前 Employee 菜单同时包含：
- My Dashboard；
- Employees；
- Organization Chart；
- Requests；
- Work Schedules；
- Policies & Discipline；
- Configuration。

这混合了 SELF、manager、admin 三种语义。
HR17 必须重构为 role-aware portal：
普通员工只看 SELF 服务；
管理功能继续归 HR01/具体管理模块。

# 10. Horilla 当前 dashboard 问题

`employee/dashboard.py` 当前读取全员：
- total/active/inactive；
- department；
- gender；
- type；
- job position；
- joining trend；
- headcount trend；
- recent employees；
- upcoming birthdays。

这些属于 HR01/组织管理/文化服务，不是普通员工 ESS 首屏。
因此 HR17 必须 REWRITE 首页数据源。

# 11. 接管策略冻结

```text
strategy = REWRITE

KEEP:
- login/session
- some shared UI
- accessibility utilities
- request/notification foundations
- existing routes as redirects

ADAPT:
- employee sidebar
- My Dashboard
- Requests
- Work Schedules self views
- documents/self views
- notifications

NEW:
- SelfIdentityContext
- SelfServiceCatalog
- SelfBootstrap
- SelfRead Provider Gateway
- SelfAction Registry
- SelfDocument Hub
- Cross-domain Timeline
- Service Search
- Retiree Access Profile
- Provider freshness/error contract
```

# 12. HR01 边界

HR01 是人事处管理工作台；普通教职工不进入 HR01。HR17 不显示全校管理 KPI。

# 13. HR02 边界

HR17 可只读展示本人当前组织/岗位名称及组织通讯录允许字段；组织/岗位设置 Authority 仍在 HR02。

# 14. HR03 边界

HR17 的“我的档案”读取 HR03。
修改分三类：
- SELF_EDITABLE：验证后直接通过 HR03 SelfUpdate API；
- REVIEW_REQUIRED：发 HR03 CorrectionRequest；
- READ_ONLY_AUTHORITY：只能查看并提示去正式业务办理。

HR17 不直接写 HR03 表。

# 15. HR05 边界

新员工 onboarding 尚未完全激活时可通过受限 pre-employee portal 查看本人入职任务；HR05 Authority 不迁入 HR17。

# 16. HR06 边界

本人可查看已生效异动/待本人确认事项；调岗、调动申请若学校允许由 HR06 SelfAction 暴露。

# 17. HR07 边界

HR17“我的合同”只读 HR07：
`ACTIVE/SIGNED_WAITING_EFFECTIVE/EXPIRED/TERMINATED` 等真实状态。
下载使用 ticket/signed URL。
续签意愿/本人确认等 action 调 HR07。

# 18. HR08 边界

兼职/外聘人员若拥有 portal identity，HR17 根据 Engagement 权限展示有限服务；不强制拥有正式 staff 全套服务。

# 19. HR09 边界

展示本人教师资格、双师型、技能资格等正式 facts；认定/复核/材料补正动作回 HR09。

# 20. HR10 边界

展示培训计划、报名、学习/实践记录、已验证发展档案；报名/补交成果回 HR10。

# 21. HR11 边界

高频 SELF：
- 今日/本月考勤摘要；
- 请假；
- 补卡；
- 加班；
- 调休；
- 假期余额；
- 申请进度。

所有状态和余额来自 HR11。

# 22. HR12 边界

展示本人年度/聘期正式结果、待确认/申诉入口、允许公开的评议内容；匿名反馈与私密 calibration 不泄露。

# 23. HR13 边界

展示职称申报进度、资格补正、正式结果和历史；HR17 不重算资格/评分。

# 24. HR14 边界

展示当前岗位聘任、竞聘批次/本人申请/拟聘/正式结果；PROPOSED 与 EFFECTIVE 明确区分。

# 25. HR15 边界

展示本人：
- 最近工资条；
- 薪酬项目解释；
- payment status；
- 社保/公积金本人侧；
- payment account mask；
- tax summary/允许文件。

金额计算全部 HR15。

# 26. HR16 边界

本人辞职/退休申请、离校任务、证明进度由 HR16 Authority；HR17 提供入口和统一状态。退休后日常服务由 HR17。

# 27. HR18 边界

HR18 是人事数据中心/正式上报，不向普通员工开放学校级统计；HR17 只显示本人依法/按政策可见的数据。

# 28. IAM 边界

IAM 提供登录、MFA、session、retiree access profile；HR17 不管理账号底层权限。

# 29. Document Provider 边界

HR17 是文件目录与下载入口；正式文件 bytes/version/signature/hash 由源域/Document Provider 管理。

# 30. SelfIdentityContext

每个 `/self` 请求先解析：
```text
tenant_id
user_id
person_id
staff_id
active_employment_relationship_ids
primary_relationship_id
engagement_ids
retirement_fact_id
portal_profile_type
permissions
assurance_level
session_id
```

# 31. SELF Resolver 失败策略

没有 staff/engagement/retiree mapping → `SELF_IDENTITY_NOT_RESOLVED`，不得 fallback 第一个 Employee。

# 32. 多关系 Employment Switcher

一个人可：
- 主聘关系；
- 兼聘关系；
- 返聘新关系；
- 多法人关系。

Portal 提供 employment switcher，但只有本人合法关系。
每个 card 显示当前 relationship context。

# 33. Retiree Context

退休人员可无 active EmploymentRelationship，但通过 RetirementFact + RetireeAccessProfile 获得有限 SELF 服务。

# 34. External/Part-time Context

HR08 external engagement 可映射 portal profile；只开放合同/报酬/任务等授权服务。

# 35. Assurance Level

敏感动作可要求：
`SESSION / PASSWORD_REAUTH / MFA / IDENTITY_VERIFIED`。
例如：
- 改银行卡；
- 下载高敏文件；
- 提交退休；
- 导出完整个人档案。

# 36. Impersonation

生产默认禁用；若客服/HR 需要 on-behalf，必须显式权限、本人/工单依据、banner、全审计、敏感工资默认不可见。

# 37. HR17-01 业务目标

打开首页 10 秒内知道“今天要做什么、最近发生了什么、最常用服务在哪里”。

# 38. 首页结构

```text
[你好，张老师] [当前关系：在职专任教师]
------------------------------------------------
重要提醒 / 待我处理（最多 3–5）
------------------------------------------------
常用服务：请假 | 工资条 | 我的合同 | 信息更正 | 培训 | 更多
------------------------------------------------
我的人事状态摘要
合同 / 岗位 / 考核 / 职称 / 薪酬 / 休假
------------------------------------------------
最近办理
------------------------------------------------
消息与公告
------------------------------------------------
服务搜索 / 帮助
```

# 39. Bootstrap API

`GET /api/v1/hr/self/bootstrap`

一次返回：
- identity；
- primary status；
- top actions；
- top alerts；
- service shortcuts；
- recent cases；
- recent documents；
- provider health summary；
- feature flags。

非首屏内容 lazy load。

# 40. 首页不显示管理 KPI

禁止 total employees、gender、department ranking、headcount trend 等。

# 41. 我的状态摘要

只展示对本人有用：
- 当前组织/岗位；
- 当前合同状态/到期；
- 当前岗位聘任；
- 最近考核结果；
- 当前职称；
- 假期余额；
- 最近工资条是否已发布；
- 下一退休预审提醒（若适用）。

# 42. Top Action Contract

每条：
```text
actionId
sourceDomain
title
description
dueAt
severity
status
route
canAct
actionType
sourceUpdatedAt
```

# 43. 我的待办聚合

只聚合各域“当前由本人处理”的 task/action，不复制状态机；source task 完成后 HR17 自动消失。

# 44. 重要提醒

如合同到期、考核确认、职称补正、竞聘材料、退休预审、工资支付异常；severity/versioned。

# 45. 常用服务

tenant 可配置排序；系统学习最近使用只能影响排序，不改变权限。

# 46. 最近办理

统一 CaseSummary：domain/caseNo/title/status/updatedAt/nextAction；点击回源域详情。

# 47. 消息中心摘要

业务消息/系统公告分离；已读仅消息状态，不改业务任务。

# 48. 生日/周年

仅本人可见或按关怀 policy；不在首页泄露同事 DOB。

# 49. 服务搜索

搜“工资”“收入证明”“改手机号”“退休”“请假”等，返回真实 service/action/document/help。

# 50. 移动首页

最多 1 屏关键事项 + 6–8 高频入口；底部导航建议：首页 / 办理 / 消息 / 我的。

# 51. 离线/弱网

移动端可缓存非敏感服务目录和最近摘要；工资/合同等敏感内容不持久化明文离线。

# 52. HR17-01 UI 路由

```text
/hr/self
/hr/self/todos
/hr/self/messages
/hr/self/services
/hr/self/search
```

# 53. HR17-02 业务目标

让教职工知道“学校记录的我是什么样”，并能安全修正常见信息而不破坏正式人事历史。

# 54. 档案摘要

照片、姓名、工号、人员类别、组织、岗位、入职/当前关系状态；权威字段标记来源。

# 55. 字段 SelfEditPolicy

每字段配置：
```text
READ_ONLY
SELF_EDIT_WITH_VALIDATION
SELF_EDIT_REQUIRES_REAUTH
CORRECTION_REQUEST
SOURCE_DOMAIN_ACTION
HIDDEN
```

# 56. 联系方式

手机号/个人邮箱/通讯地址等可按 tenant policy 自助修改；关键联系方式需 OTP/重新认证。

# 57. 紧急联系人

可本人维护，但要最小化字段、用途说明、访问权限。

# 58. 姓名/证件

姓名、身份证件等高风险更正走 HR03 CorrectionRequest + 证明材料 + 审核；不能直接 edit。

# 59. 学历学位

正式学历学位 facts READ_ONLY；新增/更正走 HR03/credential process，保留证据。

# 60. 家庭/依赖信息

只有确有业务目的的字段才开放；不可为了“档案完整”无限收集。

# 61. 头像

可自助上传，文件 scan/crop/size；不影响正式证件照字段，若二者区分则明确。

# 62. 材料中心

本人可查看允许的已归档材料目录；高敏材料不默认可下载。

# 63. 信息完整度

只按学校确实需要的字段计算；不得用家庭/敏感数据缺失制造“档案不完整”压力。

# 64. 更正申请

HR17 调 HR03 correction API；显示 RETURNED/REVIEW/APPROVED/EFFECTIVE，补正回 HR03。

# 65. Before/After

本人提交更正时显示当前值、拟更正值、生效语义、是否影响历史/下游。

# 66. 来源标签

`HR03 / HR07 / HR14 / HR16 / MIGRATED` 等，帮助解释为何不能直接改。

# 67. 历史查看

本人可查看自己的任职/关键信息历史，敏感 audit/internal note 不暴露。

# 68. 数据副本

按政策支持本人导出可提供的个人信息副本；异步、敏感确认、watermark、短 TTL。

# 69. HR17-02 UI

```text
/hr/self/profile
/hr/self/profile/edit
/hr/self/profile/corrections
/hr/self/profile/materials
/hr/self/profile/history
```

# 70. HR17-03 业务目标

把教职工职业事实做成一条可理解时间线：我在哪个岗位、签什么合同、有哪些资格、接受过什么发展、考核/职称/聘任到了哪里。

# 71. 当前任职

读取 HR03 current Assignment + HR14 appointment projection；主岗/兼岗区分。

# 72. 任职历史

按 effective-dated timeline 展示组织/岗位/关系变化；不从 current fields 推历史。

# 73. 我的合同

HR07 current + history + signed file access；SIGNED_WAITING_EFFECTIVE/ACTIVE/EXPIRED 明确。

# 74. 合同到期提醒

HR07 alert；续聘意愿/签署等动作回源域。

# 75. 教师资格

HR09 verified credentials、有效期、状态、待续办；敏感认证材料按权限。

# 76. 双师型

HR09 recognition status、等级/类型、有效期、证据摘要；不自行认定。

# 77. 培训计划

HR10 我的年度/周期发展计划、待完成培训、已完成学时/成果。

# 78. 企业实践

HR10 项目、过程状态、已验证实践事实；申请/成果提交回 HR10。

# 79. 年度考核

HR12 formal result、周期、结果通知/确认/异议状态；计算草稿不显示为 final。

# 80. 聘期考核

HR12 final term result + next action；不展示内部 calibration 私密讨论。

# 81. 职称

HR13 current ProfessionalTitleResult + history；申报进度/补正入口。

# 82. 岗位聘任

HR14 current appointment level/term、竞聘申请、PROPOSED/FINAL/EFFECTIVE 区分。

# 83. 职业时间线

统一事件：
`JOINED / TRANSFERRED / CONTRACT_ACTIVE / QUALIFICATION_VERIFIED / TRAINING_COMPLETED / ASSESSMENT_FINAL / TITLE_EFFECTIVE / APPOINTMENT_EFFECTIVE / RETIREMENT_EFFECTIVE`。

只做 projection，事件原始 Authority 保留。

# 84. 成长地图

可展示“资格→培训→考核→职称→岗位”的事实关系，但禁止黑箱评分“晋升概率”。

# 85. 缺口提示

只基于明确 policy/provider 返回，例如职称申报缺培训事实；不让 AI 自行推断资格。

# 86. HR17-03 UI

```text
/hr/self/career
/hr/self/assignments
/hr/self/contracts
/hr/self/credentials
/hr/self/development
/hr/self/assessments
/hr/self/titles
/hr/self/appointments
```

# 87. HR17-04 业务目标

把“我的工资、社保公积金、合同/证明/正式文件”集中到本人安全文件与权益中心。

# 88. 薪酬摘要

读取 HR15 FINAL/CLOSED；显示本期工资条状态、实发、支付状态、主要项目，不自己算。

# 89. 工资条

本人列表按 period；工资条 document version + result version；支持 mobile/PDF。

# 90. 工资解释

每项显示 HR15 explanation/source category；AI 可辅助解释术语，不编造金额来源。

# 91. 支付状态

CALCULATED/FINAL/PAYMENT_PENDING/PAID/FAILED 分开；工资条发布不等于已付款。

# 92. 社保

本人侧展示缴费基数、个人/单位金额、期间、申报状态；数据来自 HR15。

# 93. 公积金

同上；账户敏感标识 mask。

# 94. 个税摘要

只展示本人扣缴汇总/允许文件，不在 HR17 收集家庭专项附加扣除详情。

# 95. 银行卡

仅 last4/bank/verification/status；变更跳 HR15 高 assurance flow。

# 96. 我的文件中心

聚合：
- HR07 合同；
- HR15 工资条/收入相关文件；
- HR16 离职/退休证明；
- HR03 人事证明；
- HR09/10/12/13/14 可出具文件；
- tenant custom documents。

# 97. DocumentDescriptor

```text
documentId
sourceDomain
documentType
title
period
issuedAt
status
version
sensitivity
canPreview
canDownload
requiresReauth
verificationAvailable
sourceUpdatedAt
```

# 98. 证明申请

ServiceCatalog 中发起；真正生成由 CertificateProvider/源域负责。

# 99. 证明模板

在职证明、任职证明、收入相关证明等由 source/template Authority 管理；HR17 不拼 Word 文本。

# 100. 下载 Ticket

POST download-ticket → short-lived signed URL；ticket 与 user/staff/document/session 绑定。

# 101. 水印

敏感个人文件可带姓名/工号/下载时间/用途 watermark；不覆盖原始正式文件。

# 102. 文件验证

二维码/verification endpoint 返回最小真实性信息。

# 103. 历史文件

新模板不重渲染旧已签发文件；显示 version/superseded/revoked。

# 104. HR17-04 UI

```text
/hr/self/pay
/hr/self/payslips
/hr/self/statutory
/hr/self/documents
/hr/self/certificates
```

# 105. HR17-05 业务目标

把所有“我要办事”统一为服务目录和本人进度，但每个业务仍回源域处理。

# 106. Service Catalog

`SelfServiceDefinition`：
- service code；
- name；
- keywords/synonyms；
- source domain；
- action type；
- eligibility provider；
- route；
- form mode；
- assurance；
- required docs；
- SLA info；
- enabled roles；
- tenant overrides。

# 107. 服务分类

建议用户语言：
- 个人信息；
- 考勤休假；
- 合同任职；
- 培训发展；
- 考核；
- 职称聘任；
- 薪酬福利；
- 证明文件；
- 离职退休；
- 其他服务。

# 108. Quick Action

仅适合 3–8 个核心字段、风险低、单一目的的动作；复杂业务跳 source full page。

# 109. Service Eligibility

每个服务先调用 eligibility；不适用时说明原因，不只是隐藏。

# 110. Action Contract

```text
serviceCode
sourceDomain
eligible
reasonCode
requiredAssurance
startUrl/actionEndpoint
draftSupported
withdrawSupported
expectedSla
requiredDocuments
sourceStatus
```

# 111. 统一“我的办理”

聚合各域 CaseSummary；DB/Provider 分页，不拉全部后 Python 合并。

# 112. CaseSummary

```text
caseId
sourceDomain
serviceCode
title
status
statusLabel
submittedAt
updatedAt
nextAction
canWithdraw
canSupplement
route
```

# 113. 待补正

RETURNED case 聚合到首页；补正直接进入 source versioned application。

# 114. 撤回

只显示 source 返回 `canWithdraw=true`；HR17 不根据 status 猜。

# 115. 待确认

考核结果确认、合同签署、材料确认等都以 source task contract 聚合。

# 116. 请假

高频 Quick Action/Full Flow 由 HR11；余额/规则/审批状态实时读取。

# 117. 补卡

HR11 action；HR17 不以缺卡判断理由。

# 118. 培训报名

HR10 service；显示 eligibility/deadline。

# 119. 职称申报

HR13 full page；HR17 只提供入口、资格预检摘要、deadline、进度。

# 120. 岗位竞聘

HR14 full page；显示可申请批次和当前申请。

# 121. 信息更正

HR03 correction；常用字段可 Quick Action。

# 122. 辞职

HR16 self resignation；高 assurance + 二次确认 + notice explanation。

# 123. 退休

HR16 retirement intent/case；只在 eligibility/forecast 支持时展示对应 action。

# 124. 帮助入口

每个 Service Definition 关联 help article/FAQ/contact；帮助内容按当前功能版本。

# 125. Service Search

同义词：工资单=工资条、收入证明=薪资证明、离岗=离职等；无权限结果不得泄露隐藏服务。

# 126. 无结果兜底

进入 HR Service Case/联系入口，而不是假的“智能回答已办理”。

# 127. HR17-05 UI

```text
/hr/self/services
/hr/self/services/{code}
/hr/self/cases
/hr/self/cases/{source}/{id}
```

# 128. HR17-06 业务目标

把低频但重要的关怀、生命周期提示和退休后日常服务放到正确位置，不污染人事管理工作台。

# 129. 关怀内容边界

生日、入职周年、荣誉/活动等可配置；必须尊重隐私和文化偏好。

# 130. 本人生日

可显示给本人；同事生日是否显示由 tenant privacy policy，不默认全员可见。

# 131. 服务公告

人事政策、培训、体检、福利、退休服务等面向目标人群发布；targeting 不泄露敏感分类。

# 132. 福利活动

若学校有体检/慰问/活动 Provider，可作为 ServiceDefinition；HR17 不自建完整福利资金系统。

# 133. 退休预审提醒

读取 HR16 Forecast；显示“预计日期/需核验项/下一步”，明确不是正式退休决定。

# 134. 弹性退休入口

HR16 eligibility 返回允许后才显示；本人提交正式 intent 至 HR16。

# 135. 退休后账户

IAM RetireeAccessProfile 独立：只保留允许的工资条历史、合同/证明、退休服务、消息等。

# 136. 退休后工资条历史

HR15 本人历史只读；不保留在职 Payroll 管理权限。

# 137. 退休后证明

HR16/Document Provider 允许的退休证明/历史证明；短期签名下载。

# 138. 退休服务目录

慰问活动、证明、联系方式变更、返聘咨询等；tenant 可扩展。

# 139. 返聘 referral

HR16/HR05/HR08 action；HR17 展示进度，不把 retired 改 active。

# 140. 退休人员联系方式

若允许自助更新，写入服务联系 profile/HR03 合法字段，不修改历史任职事实。

# 141. 离职后有限访问

按 policy 可保留一定期限的工资条/证明入口；与 retiree profile 分开。

# 142. 访问到期

Retiree/Alumni access expiry 由 IAM policy，提前提醒、可续权 service case。

# 143. HR17-06 UI

```text
/hr/self/care
/hr/self/retirement
/hr/self/retiree-services
/hr/self/rehire
```

# 144. 核心模型总表

HR17 尽量不复制业务实体，只保存体验层配置/投影/用户偏好：

```text
HrSelfServiceDefinition
HrSelfServiceDefinitionVersion
HrSelfServiceCategory
HrSelfServiceKeyword
HrSelfServiceEligibilityCache
HrSelfIdentityContextSnapshot
HrSelfPortalProfile
HrSelfPortalPreference
HrSelfDashboardLayoutPreference
HrSelfShortcutPreference
HrSelfRecentService
HrSelfActionProjection
HrSelfCaseProjection
HrSelfDocumentProjection
HrSelfTimelineProjection
HrSelfMessageProjection
HrSelfNotificationPreference
HrSelfSearchIndexEntry
HrSelfHelpBinding
HrRetireeAccessProjection
HrSelfSupportCaseLink
HrSelfSensitiveAccessAudit
```

**禁止新增**：
`HrSelfContract / HrSelfPayslip / HrSelfAssessment / HrSelfTitle / HrSelfAppointment`
这类复制 Authority 的表。

# 145. Projection 原则

Projection 可重建、带 sourceDomain/sourceId/sourceVersion/sourceUpdatedAt；源域删除/更正按 event 更新。

# 146. Provider Status

`OK / PARTIAL / UNAVAILABLE / STALE / ERROR / NOT_APPLICABLE`；UI 明确展示。

# 147. 首页 Partial Success

一个 Provider 失败不导致首页整体 500；对应卡片显示“暂不可用/稍后重试”，并记录 error code。

# 148. Freshness

工资/合同/当前岗位/考核等显示 sourceUpdatedAt；关键状态 action 前强制实时确认。

# 149. 缓存

ServiceCatalog 可长缓存；Bootstrap 短缓存；工资条/敏感文档 descriptor 只缓存必要元数据；下载 URL 不缓存。

# 150. SELF Permission

普通 self read/action 权限与管理权限分离；有 `employee.view_employee` 不代表自助接口可看任意对象。

# 151. 权限代码

```text
hr.self.portal.access
hr.self.profile.view
hr.self.profile.edit_allowed
hr.self.profile.correction.create
hr.self.career.view
hr.self.contract.view
hr.self.document.view
hr.self.document.download
hr.self.pay.view
hr.self.payslip.view
hr.self.service.use
hr.self.case.view
hr.self.retirement.view
hr.self.retiree.access
hr.self.data_copy.request
```

# 152. 字段级权限

敏感字段使用 `mask / reveal-with-reauth / hidden`；不能仅页面级权限。

# 153. Step-up Authentication

银行卡、完整证件、敏感文件、数据副本、辞职/退休提交等可要求 MFA/reauth。

# 154. CSRF

所有 cookie session 写操作 CSRF；移动 token 场景按 OAuth/PKCE 等安全机制。

# 155. IDOR

document/case/action route 每次用 SelfIdentityContext 验证 ownership，不信 path id。

# 156. Mass Assignment

Self update endpoint 使用 field allowlist；客户端多传 authority field 直接拒绝。

# 157. XSS

服务公告、帮助、source narrative、工资解释必须 safe render/sanitize。

# 158. 文件安全

private storage、scan、signed URL、短 TTL、watermark、download audit、content-disposition。

# 159. 审计

self 修改、提交、撤回、下载敏感文件、查看 reveal 字段、impersonation、data copy 都审计。

# 160. 通知偏好

业务法定/重要通知不能因用户关闭营销/关怀通知而被关闭；类型分层。

# 161. 消息去重

`sourceDomain + sourceEventId + recipient + templateVersion`。

# 162. Deep Link

消息/搜索/待办 route 必须 source-safe；登录后恢复 intended route，且再次检查权限。

# 163. API Envelope

```json
{
  "apiVersion":"v1",
  "schemaVersion":"hr17.1",
  "requestId":"...",
  "data":{},
  "meta":{"sourceStatus":"OK"}
}
```

# 164. 错误码

```text
SELF_IDENTITY_NOT_RESOLVED
MULTIPLE_RELATIONSHIP_SELECTION_REQUIRED
SELF_ACCESS_DENIED
STEP_UP_AUTH_REQUIRED
FIELD_NOT_SELF_EDITABLE
CORRECTION_REQUIRED
SOURCE_UNAVAILABLE
SOURCE_STALE
SERVICE_NOT_ELIGIBLE
SERVICE_DISABLED
CASE_NOT_OWNED
ACTION_NOT_ALLOWED
DOCUMENT_NOT_OWNED
DOCUMENT_REAUTH_REQUIRED
DOCUMENT_EXPIRED
RETIREE_ACCESS_DENIED
PROJECTION_STALE
```

# 165. Service Registry

source module 向 HR17 注册 service/action/document/read provider；HR17 不在代码里散落 if domain enabled。

# 166. Feature Flags

tenant/module/role/relationship/retiree profile 综合判定；无模块时服务显示不可用或隐藏按 policy。

# 167. 配置版本

ServiceDefinitionVersion PUBLISHED immutable；keywords/help/fields/security requirement 版本化。

# 168. 搜索权限过滤

先取可访问 Service/Search Entry，再排序；不能先全局搜再前端隐藏。

# 169. 搜索索引

索引 service metadata/help titles，不索引工资明细/合同正文/敏感人事数据。

# 170. 服务推荐

基于角色、生命周期、最近使用、待办；不基于敏感健康/家庭/工资信息。

# 171. 无障碍

键盘、焦点、标签、status text、screen reader、可放大、移动触控尺寸、PDF替代说明。

# 172. Visual Regression

`375/768/1280/1440` + active/retiree/external/no-data/partial/stale/error/reauth/permission。

# 173. 移动优先

首页、待办、请假、工资条、合同、证明、信息更正、退休进度优先；复杂职称/竞聘可跳 PC-friendly full page。

# 174. 性能预算

建议：
- bootstrap p95 < 700ms；
- service search p95 < 300ms；
- case list p95 < 500ms；
- profile p95 < 500ms；
- document list p95 < 500ms；
- payslip descriptor p95 < 500ms；
- 首屏 <= 1 bootstrap + 必要静态资源；
- lazy sections 不阻塞 TTI；
- 禁止 N+1。

# 175. 可观测性

```text
self_bootstrap_latency
self_bootstrap_partial_total
self_identity_resolution_failed_total
self_service_search_no_result_total
self_action_start_failed_total
self_case_projection_lag_seconds
self_document_download_failed_total
self_sensitive_reveal_total
self_stepup_failed_total
self_provider_unavailable_total
self_retiree_access_denied_total
self_legacy_route_hit_total
```

# 176. Data Quality

- self projection source missing
- case projection status drift
- document projection points revoked source
- retiree access but no RetirementFact
- active relationship but portal profile retired
- salary card from non-final result
- contract card status drift
- cross-tenant projection
- orphan service definition

# 177. Retention

Portal preference/recent service 可短期；业务文件/事实不由 HR17 retention；search logs 最小化；sensitive reveal logs 按安全政策。

# 178. 隐私分析

新 Service 若聚合敏感数据需做 purpose/minimization/role/access review，不能只因“本人门户”就全部放一起。

# 179. 国际化

中文为主；日期、金额、状态、时区统一；英文 fallback 可保留 Horilla i18n。

# 180. 品牌

tenantBrandConfig 控制学校名称/logo/服务中心名称；不得影响 Authority/权限。

# 181. Bootstrap API

`GET /api/v1/hr/self/bootstrap`。

# 182. Identity API

`GET /api/v1/hr/self/context`、`POST /api/v1/hr/self/context/switch-relationship`。

# 183. Profile API

```text
GET /api/v1/hr/self/profile
PATCH /api/v1/hr/self/profile/allowed-fields
POST /api/v1/hr/self/profile/corrections
GET /api/v1/hr/self/profile/history
```

# 184. Career API

```text
GET /api/v1/hr/self/career/summary
GET /api/v1/hr/self/assignments
GET /api/v1/hr/self/contracts
GET /api/v1/hr/self/credentials
GET /api/v1/hr/self/development
GET /api/v1/hr/self/assessments
GET /api/v1/hr/self/titles
GET /api/v1/hr/self/appointments
```

# 185. Pay & Document API

```text
GET /api/v1/hr/self/pay/summary
GET /api/v1/hr/self/payslips
GET /api/v1/hr/self/statutory
GET /api/v1/hr/self/documents
POST /api/v1/hr/self/documents/{id}/download-ticket
POST /api/v1/hr/self/data-copy
```

# 186. Service API

```text
GET /api/v1/hr/self/services
GET /api/v1/hr/self/services/{code}
POST /api/v1/hr/self/services/{code}/start
GET /api/v1/hr/self/cases
GET /api/v1/hr/self/todos
```

# 187. Search API

`GET /api/v1/hr/self/search?q=...` 返回 service/help/document-type/case shortcuts，不全文泄露敏感数据。

# 188. Retiree API

```text
GET /api/v1/hr/self/retirement
GET /api/v1/hr/self/retiree-services
POST /api/v1/hr/self/retiree-services/{code}/start
```

# 189. Notification API

`GET /api/v1/hr/self/messages`、read preference endpoints；已读不改业务 task。

# 190. 字段级冻结｜SelfServiceDefinition

`id tenant nullable code category source_domain action_type route assurance eligibility_provider keywords status current_version`。

# 191. 字段级冻结｜SelfServiceDefinitionVersion

`service_id version_no display_name description eligibility_config input_mode required_docs help_refs security_config effective_from/to published_at/by hash`。

# 192. 字段级冻结｜SelfPortalProfile

`tenant user person staff portal_profile_type primary_relationship retiree_fact status preferences version`。

# 193. 字段级冻结｜SelfActionProjection

`tenant user source_domain source_task_id type title due_at severity status route source_version source_updated_at projection_updated_at`。

# 194. 字段级冻结｜SelfCaseProjection

`tenant user source_domain source_case_id service_code status next_action can_withdraw can_supplement submitted_at updated_at source_version`。

# 195. 字段级冻结｜SelfDocumentProjection

`tenant user source_domain source_document_id type title period issued_at version status sensitivity reauth source_version source_updated_at`。

# 196. 字段级冻结｜SelfTimelineProjection

`tenant person source_domain source_event_id event_type effective_at title summary visibility source_version`。

# 197. 字段级冻结｜SensitiveAccessAudit

`tenant user action resource_type resource_id assurance ip/device/session request_id occurred_at`，不写敏感值。

# 198. Projection 唯一约束

`tenant + user/person + source_domain + source_id` unique；source version monotonic。

# 199. 数据库约束

- tenant not null
- service code tenant/default uniqueness
- published version immutable
- projection source ids required
- retiree profile requires valid retirement ref
- no sensitive raw document bytes
- no business status editable in HR17 projection
- cross-tenant references blocked

# 200. 关键索引

```text
(tenant_id,user_id,status)
(tenant_id,user_id,due_at)
(tenant_id,user_id,source_domain,status)
(tenant_id,service_code,status)
(tenant_id,user_id,issued_at)
(tenant_id,person_id,effective_at)
```

# 201. HR17-01 验收

- bootstrap
- identity
- top actions
- alerts
- shortcuts
- recent cases
- partial success
- search
- mobile
- no management KPI

# 202. HR17-02 验收

- profile
- field policy
- phone/email edit
- reauth
- correction request
- materials
- history
- data copy
- sensitive masking

# 203. HR17-03 验收

- assignment
- contract
- credentials
- training
- assessment
- title
- appointment
- timeline
- source status
- visibility

# 204. HR17-04 验收

- pay summary
- payslip
- payment status
- social/housing
- bank mask
- document hub
- download ticket
- verification
- version

# 205. HR17-05 验收

- catalog
- eligibility
- quick action
- complex redirect
- case projection
- RETURNED
- withdraw
- search
- help
- no duplicate state machine

# 206. HR17-06 验收

- care privacy
- retirement forecast
- flexible retirement action
- retiree access
- historical documents
- rehire referral
- access expiry

# 207. SELF IDOR 测试

- change path staff id
- change query staff id
- change body staff id
- guess document id
- guess case id
- switch relationship to another user
- retiree guessing
- external engagement guessing

# 208. Tenant 测试

- same user email different tenant
- document cross tenant
- case cross tenant
- service config cross tenant
- projection cross tenant
- retiree cross tenant

# 209. Multi-relationship 测试

- primary relation
- secondary relation
- switch
- closed relation history
- rehire new relation
- no `.first()`
- pay/contract context correct

# 210. Step-up Auth 测试

- bank reveal/change
- sensitive doc
- data copy
- resignation
- retirement
- expired reauth
- session replay

# 211. Profile Field Policy 测试

- read-only
- editable
- validation
- correction required
- hidden
- mass assignment
- source-domain action

# 212. Provider Failure 测试

- HR03
- HR07
- HR11
- HR12
- HR13
- HR14
- HR15
- HR16
- Document
- IAM
- partial bootstrap

# 213. Freshness 测试

- stale projection label
- action real-time recheck
- source newer version
- event lag
- no legacy fallback

# 214. Contract 测试

- signed waiting effective
- active
- expired
- terminated
- download ownership
- version
- revoked doc

# 215. Assessment Privacy 测试

- final result visible
- draft hidden
- anonymous feedback protected
- calibration hidden
- objection action source

# 216. Payroll Privacy 测试

- only own final
- bank mask
- tax minimum
- payslip signed URL
- payment pending vs paid
- retiree history

# 217. Document 安全测试

- ticket ownership
- TTL
- watermark
- scan
- content disposition
- reauth
- revoked/superseded
- verification minimal

# 218. Service Eligibility 测试

- eligible
- not eligible explanation
- disabled module
- source unavailable
- role mismatch
- retiree
- external
- deadline

# 219. Quick Action 测试

- field limit
- validation
- CSRF
- source idempotency
- source returns case
- no local final status
- error mapping

# 220. Search 测试

- synonyms
- Chinese phrase
- permission filter
- disabled service
- help result
- no sensitive fulltext
- no result fallback

# 221. Notification 测试

- dedupe
- business vs announcement
- read doesn't complete task
- deep link auth
- retiree targeting

# 222. Mobile 测试

- 375
- touch target
- no horizontal critical table
- payslip
- leave
- contract
- document
- retirement
- weak network

# 223. Accessibility 测试

- keyboard
- focus
- screen reader
- labels
- status text
- contrast
- zoom
- PDF alternative
- error summary

# 224. 性能测试

- bootstrap p95
- search p95
- profile p95
- case list p95
- documents p95
- no waterfall
- no N+1
- projection lag metrics

# 225. Security 测试

- CSRF
- XSS
- IDOR
- mass assignment
- open redirect
- signed URL
- session fixation
- impersonation
- rate limits
- export

# 226. Legacy Route 测试

- old ess-dashboard redirect
- old employee request self route
- old payslip self link
- old contract self link
- no admin menu leakage

# 227. Visual Regression 测试

`375/768/1280/1440` 覆盖 active/retiree/external/multi-relation/partial/stale/error/no-permission/reauth。

# 228. E2E 普通教师日常

登录 → 首页看到待确认考核/最近工资条 → 看工资条 → 返回首页 → 请假 → HR11 case → 首页 recent case → 审批后状态更新 → 看我的合同 → 下载 ticket → 退出。

# 229. E2E 信息更正

改手机号直接验证生效；改姓名触发 HR03 CorrectionRequest → RETURNED → 补材料 → APPROVED → profile source update。

# 230. E2E 职称

首页提醒职称材料补正 → HR13 full page → 补正 → source status update → HR17 case/todo projection同步。

# 231. E2E 岗位竞聘

服务搜索“竞聘” → HR14 eligibility → full flow → PROPOSED 仍显示拟聘 → EFFECTIVE 后 career current update。

# 232. E2E 合同续签

HR07 renewal task → HR17 todo → 查看合同/签署 → signed waiting effective → 到期生效 → history preserved。

# 233. E2E 工资支付异常

HR15 payslip FINAL + PAYMENT_FAILED → HR17 显示工资条已出但支付异常，不错误显示已发。

# 234. E2E 退休

HR16 forecast → HR17 retirement reminder → 查看预计区间 → 发起 intent → HR16 processing → RetirementEffective → IAM switch retiree profile → HR17 retiree services。

# 235. E2E 返聘

Retiree portal → 发 rehire referral → HR05/HR08 新关系 → IAM active staff profile + history → old RetirementFact retained。

# 236. Legacy ESS Mapping

S0 搜索 employee sidebar/dashboard、requests、documents、payroll payslip self、attendance/leave self、offboarding self、notifications；形成 `LegacyEssMapping.md`。

# 237. Legacy Dashboard 退出

全员 KPI 路由迁回/redirect HR01；普通员工 ess-dashboard 只返回 HR17 SELF bootstrap。

# 238. Legacy Menu Split

Employee 管理项与 Self Service 分离；manager/admin menu 按权限归后台，不污染普通员工导航。

# 239. Legacy Requests

现有 Requests 可作为 ServiceCatalog/source action 兼容入口；长期由各 Authority 事件/CaseSummary 聚合。

# 240. Legacy Documents

旧 Document/Payslip/Contract self links redirect HR17 Document Hub，但源文件 Authority 不迁移。

# 241. Projection Build

从 HR03–HR16 current facts/events 回填 self projection；可重建，不作为迁移真值。

# 242. DUAL_READ_COMPARE

- profile current
- contract current
- assignment current
- leave balance
- assessment final
- title
- appointment
- latest payslip
- retirement status
- case/todo counts
- document counts

# 243. Authority of Experience Cutover

```text
LEGACY_ESS_LINKS
→ HR17_SHADOW
→ DUAL_VIEW_COMPARE
→ HR17_DEFAULT_PORTAL
→ LEGACY_ROUTE_REDIRECT
→ REMOVE_LEGACY_SELF_WRITES
```

注意：业务 Authority 从未迁入 HR17，只迁“体验入口”。

# 244. Rollback

可回退入口路由，但不丢 HR17 preference/projection；source business facts 完全不受影响。

# 245. AI/智能助手边界

允许：
- 服务搜索；
- 帮助文章问答；
- 工资条项目解释（基于 HR15 source explanation）；
- 合同条款摘要（明确非法律意见）；
- 办理进度解释；
- 缺失材料提醒；
- 页面导航。

禁止：
- 编造本人事实；
- 猜工资；
- 猜退休资格；
- 猜职称资格；
- 自动作出人事决定；
- 未确认执行辞职/退休/银行卡变更；
- 泄露其他教职工数据；
- 绕过 source permission。

所有个人事实回答必须引用结构化 source；无 source 就说“当前数据不可用/未接入”，不能补想象。

# 246. 编码 AI 施工纪律

- 先读真实 ESS/employee/request/document/payroll self 代码。
- HR17 只建体验层，不复制 HR03–HR16 Authority。
- 所有 SELF 从登录态解析。
- 不使用 git add -A。
- 未经授权不 push/merge main。
- 保持 Draft PR。
- 先 identity/security/provider contracts，再页面。
- 一个 source 失败要 partial success。
- 不使用 mock/legacy fallback 冒充正式个人数据。
- 移动端与 PC 同时验收。
- 不关闭 403 修测试。

# 247. S0 输出物

```text
HR17_GAP_MATRIX.md
LegacyEssMapping.md
LegacySelfRouteMap.md
SelfIdentityMatrix.md
SelfFieldEditPolicyMatrix.md
SelfServiceCatalogMatrix.md
SelfProviderMatrix.md
SelfDocumentMatrix.md
SelfSensitiveDataMatrix.md
SelfRetireeAccessMatrix.md
HR17_PERMISSION_MATRIX.md
HR17_INTEGRATION_MATRIX.md
HR17_TASK_TREE.md
HR17_RISK_REGISTER.md
HR17_MIGRATION_PLAN.md
```

# 248. HR17-S0 基线复审

- read employee sidebar/dashboard/templates/urls
- requests/work schedules
- payroll self
- documents
- leave/attendance self
- HR03–HR16 self contracts
- IAM identity
- mobile
- audit only

# 249. HR17-S1 Identity / A0

- tenant fail-closed
- SelfIdentityContext
- multi relationship
- retiree/external profiles
- permissions
- step-up
- API/error
- audit

# 250. HR17-S2 Service Registry / Gateway

- SelfServiceDefinition
- provider contracts
- action registry
- document registry
- case/todo projection
- source status/freshness

# 251. HR17-S3 我的服务首页

- bootstrap
- top actions
- alerts
- shortcuts
- recent cases
- messages
- search
- partial success
- HR17-01 UI

# 252. HR17-S4 我的档案与更正

- profile
- field policy
- validation
- corrections
- materials
- history
- data copy
- HR17-02 UI

# 253. HR17-S5 我的任职与成长

- assignments
- contracts
- credentials
- development
- assessment
- title
- appointment
- timeline
- HR17-03 UI

# 254. HR17-S6 薪酬权益/文件

- pay summary
- payslips
- statutory
- bank mask
- document hub
- certificate
- download ticket
- HR17-04 UI

# 255. HR17-S7 我的申请与办理

- catalog
- eligibility
- quick action
- complex flow redirect
- case list
- RETURNED
- withdraw
- help
- HR17-05 UI

# 256. HR17-S8 消息/搜索/帮助

- notifications
- deep links
- search synonyms
- help binding
- support fallback
- AI boundary
- analytics privacy

# 257. HR17-S9 关怀/退休服务

- care privacy
- retirement forecast
- intent
- retiree profile
- historical documents
- rehire referral
- HR17-06 UI

# 258. HR17-S10 Mobile / Retiree / External

- 375-first flows
- weak network
- profile switch
- limited access
- session/MFA
- deep links

# 259. HR17-S11 Legacy + 全量质量

- route redirect
- dual view
- security/IDOR
- performance
- provider failure
- E2E
- A11y
- visual
- observability
- data quality

# 260. HR17-S12 Portal Cutover

- HR17 default ESS
- legacy dashboard redirect
- menu split
- source action dry run
- retiree access dry run
- rollback
- no fallback

# 261. HR17-S13 最终封板

- six workspaces green
- SELF security green
- providers green
- documents green
- mobile green
- retiree green
- legacy redirect green
- E2E/performance/observability/A11y/visual green

# 262. 附录｜首页卡片优先级

P0 待办/阻塞 > P1 即将到期 > P2 最近结果 > P3 关怀；用户不可把法定/正式待办彻底隐藏。

# 263. 附录｜首页卡片数量

首屏建议 3–5 待办 + 6–8 快捷服务，避免 20+ 彩色卡片。

# 264. 附录｜首页个性化

可调整快捷入口/模块顺序；不能隐藏 mandatory alert；偏好 tenant/user scoped。

# 265. 附录｜服务别名

工资单/薪资单→工资条；续约→续签；离岗→辞职/离校帮助；退休年龄→退休预审；改电话→联系方式修改。

# 266. 附录｜搜索日志隐私

只保存 query 最小化/匿名化统计；敏感个人内容不长期存。

# 267. 附录｜服务热度

可用于排序，但热度不能越权开放服务。

# 268. 附录｜我的组织

可显示组织名称、负责人和通讯录允许信息；不显示全员敏感信息。

# 269. 附录｜组织架构入口

组织图若对教职工开放，必须使用公开通讯录字段，不复用 HR 管理视图。

# 270. 附录｜同事目录

如启用仅姓名/职务/办公联系方式等 policy 允许字段；DOB/身份证/工资绝不进入。

# 271. 附录｜个人手机号变更

OTP/reauth + new phone verification + audit；旧值保留 HR03 history policy。

# 272. 附录｜个人邮箱变更

验证新邮箱；企业邮箱可能由 IAM Authority，不允许 HR17 直接改。

# 273. 附录｜地址变更

可 self edit or correction by field policy；影响税/社保时需下游 review。

# 274. 附录｜银行卡变更

跳 HR15 secure action；HR17 只显示 masked status。

# 275. 附录｜证件更正

高 assurance + correction + evidence；不允许 Quick Action 直接改正式证件号。

# 276. 附录｜照片

头像与正式档案照片可区分；avatar 自助修改不能覆盖 authority photo。

# 277. 附录｜家庭成员

没有明确业务用途时不采集；有用途时字段最小化。

# 278. 附录｜我的合同

按 HR07 root/term/version 展示；历史合同可查，终止不删除。

# 279. 附录｜合同下载

每次 download-ticket 绑定 current identity，管理员分享的裸链接无效。

# 280. 附录｜我的考核

只显示 HR12 明确 subject-visible 内容；calibration/reviewer confidential 保持边界。

# 281. 附录｜我的职称

申请/评审中状态按 HR13 disclosure policy；不展示保密专家票。

# 282. 附录｜我的聘任

拟聘、公示、final、effective 状态文案清晰，不把拟聘当现任岗位。

# 283. 附录｜培训学时

只显示 HR10 verified/accepted facts；self-reported 待核验需标签。

# 284. 附录｜资格到期

HR09 expiry alert 可在首页出现，点击进入续办/复核 service。

# 285. 附录｜工资条可解释性

每项来自 HR15 line explanation；HR17 可以用户语言重写展示，但数字/规则来源不可更改。

# 286. 附录｜工资同比/环比

本人可选展示本月较上月差异，但不得根据同事工资做排名/比较。

# 287. 附录｜薪酬隐私

浏览器 history/title/analytics 不记录工资金额。

# 288. 附录｜工资条打印

PDF/打印页面 no-cache；打印后风险由用户自担但系统不把 URL 长期有效。

# 289. 附录｜社保公积金

显示 Provider/HR15 最终申报状态，不把 calculated 当 agency accepted。

# 290. 附录｜收入证明

金额若需要以 HR15 final facts生成；模板/签章由 CertificateProvider。

# 291. 附录｜在职证明

HR03 Employment active + template version；不能只看 `employee.is_active`。

# 292. 附录｜任职证明

HR03/HR14 effective facts + as-of；历史任职证明按日期生成。

# 293. 附录｜职称证明

HR13 effective Result；撤销后验证端显示 revoked/superseded。

# 294. 附录｜证明用途

可让用户选择用途作为水印/申请参数，但不允许自由编辑正式正文。

# 295. 附录｜数据副本导出

异步 ZIP/PDF/JSON 视学校政策，文件 manifest + TTL + MFA；不含他人数据和内部保密意见。

# 296. 附录｜请假 Quick Action

仅当 HR11 schema 简单且完整；复杂跨日期/附件/特殊假种跳 full page。

# 297. 附录｜补卡 Quick Action

显示缺卡事实由 HR11提供；理由/附件提交回 HR11。

# 298. 附录｜考勤争议

跳 HR11 correction/dispute，不在 HR17 备注里改考勤。

# 299. 附录｜培训报名

显示 seats/deadline/eligibility 来自 HR10；报名回执 source case。

# 300. 附录｜考核确认

确认/不同意/申诉 action 由 HR12；HR17 不解释为“已同意所有内容”。

# 301. 附录｜职称补正

首页 todo 可提醒具体缺项；点击后 source application version。

# 302. 附录｜竞聘补正

同上，HR14 source。

# 303. 附录｜辞职二次确认

明确 planned date、notice、不可逆阶段和 contact；需要 reauth。

# 304. 附录｜退休意向

明确 forecast ≠ approval；选择日期需 HR16 eligibility/official window。

# 305. 附录｜Service Case

若无法自动办理，创建 HR 服务咨询工单；工单不替代正式业务 Case。

# 306. 附录｜帮助中心

帮助文章必须与 source module 当前状态机/菜单一致；废弃入口文章下线。

# 307. 附录｜FAQ 版本

ArticleVersion + applicable feature/version/role；搜索不返回过时规则。

# 308. 附录｜AI 助手检索

只基于当前帮助文章 + 本人结构化 source；个人事实回答必须 tool-grounded。

# 309. 附录｜AI 敏感确认

涉及写操作必须展示将要提交的字段/目标 source，用户明确确认后调用 action。

# 310. 附录｜AI 无数据

Provider unavailable 只能说不可用，不能根据历史/通识猜当前工资、合同或退休状态。

# 311. 附录｜消息分类

`ACTION_REQUIRED / RESULT / DEADLINE / PAYMENT / DOCUMENT / POLICY / CARE / SYSTEM`。

# 312. 附录｜强制消息

合同签署、考核确认、工资支付异常、退休审批等不能被普通营销通知开关屏蔽。

# 313. 附录｜消息已读

read receipt 独立，不传播 source business status。

# 314. 附录｜移动 Push

push 只放最小标题，不在锁屏泄露工资金额/处分/敏感原因。

# 315. 附录｜微信小程序适配

若后续接教师小程序，复用 `/self` contracts，不另建 mock mobile API。

# 316. 附录｜PC/移动一致性

同一 source status/permission/action contract；移动只缩功能，不改业务真值。

# 317. 附录｜Retiree Access

退休后自动从 active ESS 转 limited retiree profile；保留哪些服务 tenant policy versioned。

# 318. 附录｜离职后访问

可配置有限时间查看工资条/证明，IAM policy 独立于 Retiree profile。

# 319. 附录｜返聘后切换

新 relationship 激活后 portal 可显示 active + history；RetirementFact 仍在 career timeline。

# 320. 附录｜多法人

一个账号可跨法人 relationship 时 tenant/company context 明确，工资/合同文件不能串。

# 321. 附录｜代理办理

on-behalf 需明确授权；普通 manager 不能以“帮助员工”为由查看工资/身份证。

# 322. 附录｜客服模式

客服只能看技术状态/服务 code/requestId；若要看个人敏感内容必须 break-glass + reason + audit。

# 323. 附录｜Break-glass

高权限紧急访问有时限、审批/理由、banner、全日志、事后复核。

# 324. 附录｜浏览器安全

sensitive pages Cache-Control no-store，防 clickjacking/CSP/secure cookies。

# 325. 附录｜下载安全

ticket 一次/短期可用；download audit；对象 storage key 不暴露。

# 326. 附录｜截图风险提示

工资条等可提示用户保护隐私，但不能阻止所有系统级截图当作安全假设。

# 327. 附录｜生日关怀

从 HR01 移出后可作为 HR17 CARE 卡；默认本人或受控群体，不形成全校生日名单。

# 328. 附录｜文化关怀退出

允许用户关闭非必要关怀通知；不影响法定/业务通知。

# 329. 附录｜服务满意度

办理完成后可收集服务体验，不改变 source result；匿名/实名由 policy。

# 330. 附录｜NPS/评价边界

不得用个人工资/考核结果作为服务满意度 targeting。

# 331. 附录｜首页空态

没有待办时显示“当前无需处理”+ 常用服务，而不是造假数据。

# 332. 附录｜Provider 错误态

卡片显示具体“工资服务暂不可用”，其他卡片继续；提供 requestId/重试。

# 333. 附录｜STALE 态

显示最后更新时间；敏感 action 启动前强制 source refresh。

# 334. 附录｜PARTIAL 态

如发展档案只接 HR10 未接科研，明确缺失来源，不显示“全部完成”。

# 335. 附录｜Service SLA

展示预计处理时间只来自 source policy，不由 HR17 自己承诺。

# 336. 附录｜倒计时

仅辅助；必须同时显示绝对日期和时区。

# 337. 附录｜历史 Timeline

可合并多个 domain event，但排序按 effective_at；created_at 只用于审计。

# 338. 附录｜Timeline 去重

同一业务事件经多个 projection 不重复显示；event correlation id。

# 339. 附录｜Timeline 隐私

处分/敏感解除等不默认出现在普通职业时间线，按 visibility policy。

# 340. 附录｜个人数据复制权

请求状态/范围/文件过期均可追踪；复杂法律例外交合规流程。

# 341. 附录｜更正权

HR17 提供入口但 source Authority 决定直接改/审核/拒绝及历史处理。

# 342. 附录｜账户注销边界

离职/退休不等于删除 Person；IAM 账号注销/停用和人事 retention 分离。

# 343. 附录｜审计可见性

本人不自动看到内部安全审计日志；可按政策显示自己的关键操作历史。

# 344. 附录｜异常访问监控

大量工资条下载、跨 document 猜测、反复 step-up 失败触发安全告警。

# 345. 附录｜Rate Limit

search/download-ticket/OTP/sensitive reveal/data-copy 分别限流。

# 346. 附录｜Session

高敏页面 session idle timeout 可短于普通门户；MFA assurance 有独立 TTL。

# 347. 附录｜设备信任

若接 IAM trusted device，只作为 assurance 信号，不由 HR17 自造设备安全判断。

# 348. 附录｜数据分析

只做服务使用率、失败率、搜索无结果、办理转化等体验指标；不做人事绩效黑箱画像。

# 349. 附录｜搜索无结果改进

收集匿名 query→人工维护 keyword/help，不让 AI 自动新增业务规则。

# 350. 附录｜服务目录发布 Gate

source endpoint exists、permission contract、eligibility、help、analytics privacy、mobile behavior、error handling 全部通过才 PUBLISHED。

# 351. 附录｜Projection Reconciliation

每日抽查 source current vs HR17 projection；drift 自动重建/报警，不手工改 projection。

# 352. 附录｜事件丢失恢复

可按 source updated_at 增量回扫；projection 可重建。

# 353. 附录｜灾难恢复

HR17 preference/projection 丢失可从 source 重建；业务事实不受影响。

# 354. 附录｜上线后七日监控

identity fail、403、partial bootstrap、projection lag、download errors、search no-result、legacy route、retiree access。

# 355. 附录｜商业化验收

- 普通教师不需要进入人事后台即可完成高频自助
- 一个首页能看清本人当前关键状态和待办
- 一个搜索能找到真实服务
- 个人资料可改与不可改边界清楚
- 合同/考核/职称/岗位/工资不复制、不串状态
- 工资条和证明下载安全
- 复杂业务能无缝跳源模块并返回进度
- 移动端高频任务真正可用
- 退休后服务不保留在职权限
- 任何 Provider 失败都不会伪造事实

# 356. 最终封板条件

## 业务
- 六个三级模块完整；
- 首页/待办/服务搜索；
- 我的档案/更正；
- 任职/合同/资格/发展/考核/职称/聘任；
- 工资条/社保公积金/文件证明；
- 服务目录/申请/进度/补正/撤回；
- 关怀/退休/返聘入口；
- PC + mobile。

## Authority
- HR17 不复制 HR03–HR16 业务真值；
- `/self` 全部由身份解析；
- Projection 可重建；
- source status/freshness 明确；
- no silent legacy fallback。

## 安全
- tenant；
- SELF IDOR；
- multi relationship；
- step-up；
- sensitive masking；
- document ticket；
- Case ownership；
- impersonation/break-glass；
- audit；
- privacy；
- no sensitive logs。

## 工程
- bootstrap partial success；
- provider contracts；
- events/projection reconciliation；
- caching；
- rate limit；
- idempotent source actions；
- legacy redirects；
- performance；
- observability。

## UX
- 首屏 10 秒可理解；
- 不展示管理 KPI；
- 不按后台模块编号组织服务；
- 服务搜索；
- 空/错/STALE/PARTIAL；
- 375/768/1280/1440；
- Accessibility；
- Visual Regression。

只有全部满足：
```text
HR17 READY FOR ACCEPTANCE
```

否则：
```text
HR17 NOT READY
blocking:
- <精确缺口>
```

# 357. 最终架构冻结图

```text
                    IAM / SelfIdentityContext
                              │
                              ▼
                       HR17 Self Gateway
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
      Self Read           Self Actions      Self Documents
           │                  │                  │
   ┌───────┼───────┐    ┌─────┼─────┐      ┌────┼────┐
   ▼       ▼       ▼    ▼     ▼     ▼      ▼    ▼    ▼
 HR03    HR07    HR15  HR11  HR13  HR16   HR07 HR15 HR16
 HR09    HR10    HR12        HR14
   │       │       │    │     │     │      │    │    │
   └───────┴───────┴────┴─────┴─────┴──────┴────┴────┘
                              │
                              ▼
                     Projection / Bootstrap
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
    服务首页/待办          我的档案/成长        薪酬/文件
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                       服务目录/搜索
                              │
                              ▼
                      PC / Mobile / Retiree

原则：
HR17 = Experience Authority
HR03–HR16 = Business Fact Authorities
```

# 358. 外部依据与成熟产品基线

S0 必须再次核验最新版本。本册当前基线：

1. 《中华人民共和国个人信息保护法》  
   重点用于 HR17 的个人信息最小必要、敏感个人信息保护、个人查阅/复制/更正等权利、安全义务。  
   https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/bgt/art/2023/art_f374e8245320413181742e6d1baf4366.html

2. 《中华人民共和国电子签名法》（2019 年修正）  
   用于电子文件、数据电文、电子签名的完整性/可调取/法律效力边界。  
   https://www.npc.gov.cn/zgrdw/npc/xinwen/2019-05/07/content_2086835.htm

3. SAP SuccessFactors Employee Central 1H 2026  
   当前 Best Practices 包含 Employee/Manager Self Service、权限、Quick Actions、Time Off/Time Sheet、Document Generation 等；ESS 明确支持员工在权限控制下修改本人信息。  
   https://help.sap.com/docs/successfactors-employee-central/solution-scope-sap-best-practices-for-sap-successfactors-employee-central/scope-details  
   https://help.sap.com/docs/successfactors-employee-central/implementing-employee-central-core/employee-self-service-ess

4. SAP Employee Central Quick Actions 1H 2026  
   强调针对角色和具体 use case 的简化操作、只展示必要字段。  
   https://help.sap.com/docs/successfactors-employee-central/implementing-employee-central-core/employee-central-quick-actions

5. Workday Employee Self-Service / Mobile（2026 当前公开产品能力）  
   强调工资与 HR 数据单入口、工资条、服务支持和移动端日常任务。  
   https://www.workday.com/en-sg/products/payroll/employee-self-service.html  
   https://www.workday.com/en-sg/products/platform-product-extensions/workday-mobile.html

跃科吸收的是方法论：
**single entry + SELF security + quick actions + authoritative source + mobile-first + explainable status**，
不照抄外国 HCM 的模块名称和政策模型。

# 359. 编码 AI 首条执行指令

```text
你现在施工 HR17 教职工服务中心。

唯一权威事实源：
17_HR17_教职工服务_施工总册_终极版.md

强制先执行 HR17-S0：

1. 读取 penghaibin9/renshi 最新目标分支真实代码；
2. 审计 employee/sidebar.py、employee/dashboard.py、employee/templates、employee/urls、requests、work schedules、documents、notifications、payroll payslip self、attendance/leave self、offboarding self 等全部现有 ESS 入口；
3. 搜索 ess-dashboard、My Dashboard、Requests、self、employee_id/staff_id query、download、payslip、contract、profile edit、organisation chart、configuration；
4. 读取 HR03–HR16 所有已冻结 Self/Provider/Action/Document contracts，尤其 HR07 `/self/contracts`、HR15 payslip/self、HR16 retirement/retiree boundary；
5. 物化 HR17_GAP_MATRIX、LegacyEssMapping、LegacySelfRouteMap、SelfIdentityMatrix、SelfFieldEditPolicyMatrix、SelfServiceCatalogMatrix、SelfProviderMatrix、SelfDocumentMatrix、SelfSensitiveDataMatrix、SelfRetireeAccessMatrix、HR17_PERMISSION_MATRIX、HR17_INTEGRATION_MATRIX、HR17_TASK_TREE、HR17_RISK_REGISTER、HR17_MIGRATION_PLAN；
6. S0 只审计和落计划，不大改代码；
7. S0 后严格按 S1→S13；
8. 首先实现 SelfIdentityContext + tenant fail-closed + multi-relationship；
9. 所有 `/self` API 禁止接受任意 staff_id 作为 Authority；
10. HR17 不新建 Contract/Payslip/Assessment/Title/Appointment/Exit 第二套业务表；
11. 首页改为单 bootstrap + partial success，禁止十几个串行小接口；
12. 普通教职工首页删除全员人数、性别、部门、岗位、recent employees 等管理 KPI；
13. Employee 管理/Configuration 从普通 ESS 导航分离；
14. ServiceCatalog 只注册真实 source action；
15. Quick Action 只用于简单低风险场景，复杂职称/竞聘/退休跳 source full page；
16. 工资条、合同、证明全部 ownership + download ticket + short TTL；
17. Provider UNAVAILABLE/STALE 必须显式，不 silent fallback legacy；
18. AI 只做导航/解释/帮助，不编造个人事实、不自动做敏感写操作；
19. PC 与 375 移动端同步验收；
20. 不关闭 403 修测试；
21. 不合并 main，不部署生产。

最终只有 HR17 六模块、SELF/tenant 安全、Provider 聚合、ServiceCatalog、文件安全、移动端、退休后访问、Legacy redirects、E2E、性能、可观测性、Accessibility、Visual Regression 全部绿色，才能输出：

HR17 READY FOR ACCEPTANCE
```

# 360. 字段规则验收样例｜手机号

SELF_EDIT_WITH_VALIDATION；新手机号 OTP 成功后写 HR03，旧值 history/audit。

# 361. 字段规则验收样例｜工号

READ_ONLY_AUTHORITY；只能显示，变更走 HR03 authorized correction。

# 362. 字段规则验收样例｜姓名

CORRECTION_REQUEST；上传必要证据，HR03 review。

# 363. 字段规则验收样例｜银行卡

SOURCE_DOMAIN_ACTION；跳 HR15，step-up auth。

# 364. 字段规则验收样例｜当前岗位

READ_ONLY_AUTHORITY；来源 HR03/HR14，不能个人修改。

# 365. 字段规则验收样例｜职称

READ_ONLY + HR13 application action；不能 self edit result。

# 366. 字段规则验收样例｜退休日期

FORECAST 只读 + HR16 action；不能个人直接覆盖。

# 367. Provider Contract｜HR03

`get_self_profile / get_self_assignments / update_allowed_fields / create_correction / get_self_history`。

# 368. Provider Contract｜HR07

`get_self_contracts / get_contract_detail / get_download_ticket / get_self_actions`。

# 369. Provider Contract｜HR09

`get_self_credentials / get_self_recognitions / get_self_actions`。

# 370. Provider Contract｜HR10

`get_self_development_summary / get_training_cases / get_practice_facts / get_actions`。

# 371. Provider Contract｜HR11

`get_self_time_summary / balances / cases / available_actions`。

# 372. Provider Contract｜HR12

`get_self_final_results / get_subject_visible_detail / get_actions`。

# 373. Provider Contract｜HR13

`get_self_title_results / applications / eligible_batches / actions`。

# 374. Provider Contract｜HR14

`get_self_appointment / applications / available_batches / actions`。

# 375. Provider Contract｜HR15

`get_self_pay_summary / payslips / statutory / payment_accounts_masked / documents`。

# 376. Provider Contract｜HR16

`get_self_exit_cases / retirement_summary / exit_tasks / retiree_services / actions`。

# 377. Source Action Result

所有 start/submit action 返回：
```text
sourceDomain
sourceCaseId
status
nextAction
route
version
requestId
```
HR17 只存 projection/ref。

# 378. 首页错误隔离

HR15 down 时工资卡不可用；合同/请假/待办仍正常。不得 bootstrap 全失败。

# 379. 首页超时预算

每 Provider 独立 timeout/circuit breaker；非关键卡超时降级为 PARTIAL。

# 380. Circuit Breaker

连续 Provider 错误短时熔断并提示，不打爆源系统；敏感 action 不走缓存替代。

# 381. Projection Lag

事件型投影 lag 超阈值 STALE；用户打开详情时回 source 强校验。

# 382. 消息与待办一致性

Todo source status 完成后即使消息未读也不再当待办；消息仍可保留结果通知。

# 383. Deep Link 回跳

source full page 完成后支持 `returnTo=/hr/self/cases`，但 returnTo 必须 allowlist 防 open redirect。

# 384. 服务目录 Tenant Override

学校可关闭/重命名/排序服务，但不能通过 UI override 绕 source permission。

# 385. 服务目录版本回滚

回滚只影响入口定义，不回滚已提交业务 Case。

# 386. 服务帮助绑定

每个 service 关联 source feature version；feature retired 后 help 自动 retired。

# 387. 政策通知

HR17 展示面向教职工的 policy announcement，但正式政策 Authority/文档另有来源。

# 388. 本人确认动作

acknowledge != approve；UI 文案精确，例如“我已知晓”不能显示“同意”。

# 389. 电子签署入口

HR07 signature provider action；HR17 只 deep link/嵌入受控签署，不保存签名秘密。

# 390. 工资条再认证

学校可对单次工资条查看不要求 MFA，但批量下载/历史完整导出要求 step-up，policy versioned。

# 391. Retiree 身份切换

退休生效后当前 active service profile 收缩；若返聘再出现 active relationship switcher。

# 392. External Teacher 服务

外聘教师按 HR08 engagement 可见合同/报酬/任务，隐藏正式员工不适用服务。

# 393. Pre-employee 服务

HR05 onboarding 期间允许受限门户，但不暴露尚未生效的 Staff Authority 为在职。

# 394. Session 生命周期

PreEmployee/Active/Retiree/External profile 切换需 IAM token/context refresh，避免旧权限残留。

# 395. 事件版本

source event 带 aggregateVersion；旧 event 不能覆盖新 projection。

# 396. Projection 重放

事件重复 10 次结果一致；event id unique。

# 397. 全量重建

提供 admin job rebuild HR17 projections；只读源 Authority，无反向写。

# 398. Bootstrap Contract 测试

schema version、optional provider sections、unknown enum fallback、partial meta、source freshness。

# 399. 移动 Deep Link

push → auth → relationship context → source action；无登录时安全恢复。

# 400. 移动工资条

正文可适配卡片/表格 + PDF；不要求用户横向滚动 20 列。

# 401. 移动合同

摘要 + 状态 + 到期 + 下载/签署 action；复杂条款 PDF/全文页。

# 402. 移动退休

显示日期说明、当前步骤、需本人处理；复杂材料管理可 PC。

# 403. 无障碍工资

金额与扣款有文本标签，负数不只用红色。

# 404. 无障碍 Timeline

时间线提供列表语义，不仅视觉轴线。

# 405. 性能压测｜1万并发登录峰值

Bootstrap cache/Provider pool/timeout 需压测；不得每人触发全域重查询。

# 406. 安全压测｜枚举下载

连续猜 document IDs 均 404/403 一致策略并触发 rate/security alert。

# 407. 安全压测｜关系切换

修改 relationship id 不能切到同工号/同姓名他人。

# 408. 审计抽样

随机 30 教师检查 bootstrap→合同→工资→申请→文件每条均可追 source。

# 409. 灾备验收

清空 HR17 projection 后可重建；源 HR03–HR16 不受影响；用户偏好恢复策略明确。

# 410. Legacy 页面封板

旧 `employee/dashboard` 普通员工请求必须 redirect HR17；后台 HR01 不复用 HR17 self data contract。

# 411. 最终商业体验

成熟后的 HR17 应让老师感受不到“18 个后台人事模块”。

老师只看到：
- **我的事**：今天要处理什么；
- **我的人**：学校记录的我；
- **我的职业**：岗位、合同、资格、发展、考核、职称、聘任；
- **我的权益**：工资、社保公积金、正式文件；
- **我要办**：请假、补卡、更正、培训、职称、竞聘、退休等；
- **我的服务**：关怀、退休后服务、帮助。

后台复杂度由 Provider/ServiceCatalog/Source Authority 吸收。

# 412. 最终封板口径再次冻结

只有 HR17-S0→S13、六个工作区 DoD、SelfIdentityContext、multi-relationship、Retiree/External/PreEmployee profiles、所有 `/self` ownership、Provider partial/freshness、ServiceCatalog、Quick Actions、工资合同文件安全、信息更正、移动端、Legacy route split、IDOR/隐私、E2E、性能、可观测性、Accessibility、Visual Regression 全部绿色且无 P0/P1 阻塞，才允许：

```text
HR17 READY FOR ACCEPTANCE
```

否则只能：

```text
HR17 NOT READY
blocking:
- <精确缺口>
```

禁止用“能登录、能看到个人信息、能请假”冒充成熟 ESS。
