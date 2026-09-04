# 05_HR05_入职管理_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API（`/api/v1/hr`）、数据库目标（MySQL-only）、事件、权限、Legacy、审计、安全和最终生产 Gate。
> PATCH-04 统一：`Authority Strategy = REWRITE`；`Legacy Technical Reuse = ADAPT`。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR05 入职管理  
> 三级模块数量：5  
> 总体接管策略：ADAPT  
> 版本：V1.0 终极冻结版  
> 文档性质：HR05 唯一权威施工事实源；可直接整份交给编码 AI 执行“Horilla Onboarding 基线复审 → Legacy 映射 → 任务拆解 → 高校入职权威模型 → API → 管理端 → 新教工门户 → 多部门协同 → HR03 正式生效 → Legacy 双读对账 → 测试 → 收口”的生产级施工。  
> 适配底座：Horilla HRMS 2.0（当前 `penghaibin9/renshi` 基线）  
> 前置标准：继承《01_HR01》《02_HR02》《03_HR03》《04_HR04》终极版的 A0 多学校 fail-closed、API 版本化、错误信封、公共 UI、Legacy 退出、异步任务、审计、可观测性、Excel、敏感字段、幂等、事务与 AI 施工纪律。  
> 重要边界：H0/A0 未封板前，HR05 只能开发不能标记生产完成；HR02 未稳定前不得正式占用岗位；HR03 未提供权威 Person/StaffMaster/Employment/Assignment Service 前不得将“报到”直接等同于“正式教职工生效”；HR04 未形成合法 handoff 的招聘来源不得直接进入正式入职。  
> 编写日期：2026-08-08  
> 核心原则：**Onboarding 是“从拟录用到正式可工作”的受控事实编排，不是 Candidate → Employee 的快捷转换。**

---

# 0. 结论先行

HR05 不是“新员工填资料”，也不是“做完几个 onboarding task”。

HR05 是高校把一个**已经具备合法入职来源的人**，经过报到确认、身份材料核验、学校主数据创建、岗位/组织生效、合同/账号/工资/门禁/校园卡等跨部门协同，最终变成“可以开始承担学校工作”的正式教职工的业务编排中心。

完整事实链冻结为：

```text
HR04 HANDOFF / 合法人工迁移来源
                ↓
HR05-01 待报到人员
    ├─ 确认入职意愿
    ├─ 预约/预计报到
    ├─ 延期
    ├─ 放弃
    └─ 到期风险
                ↓
HR05-02 报到登记
    ├─ 实际报到
    ├─ 入职来源确认
    ├─ 用工关系确认
    ├─ 组织/岗位确认
    ├─ 工号预分配
    └─ Day-1 生效计划
                ↓
HR05-03 入职材料核验
    ├─ 身份
    ├─ 学历学位
    ├─ 工作经历
    ├─ 资格证书
    ├─ 档案
    ├─ 体检/准入
    └─ 合同/协议前置材料
                ↓
HR05 正式生效闸门
    ├─ HR03 Person / StaffMaster
    ├─ EmploymentRelationship
    ├─ Assignment
    ├─ HR02 Position Reservation → COMMITTED
    ├─ Account/SSO Provisioning Event
    └─ 受控字段进入权威人事主档
                ↓
HR05-04 入职协同任务
    ├─ HR
    ├─ 学院
    ├─ IT
    ├─ 财务
    ├─ 资产
    ├─ 一卡通/门禁
    ├─ 图书/办公
    └─ 教务教师身份等
                ↓
开始工作
                ↓
HR05-05 试用与转正
    ├─ 试用目标
    ├─ 到期提醒
    ├─ 自评/单位评价
    ├─ 延长/转正/不通过
    └─ 正式归档
```

HR05 必须解决 8 个根本问题：

1. **这个人为什么有资格进入入职？**
2. **他是否真的到校报到了？**
3. **哪些材料必须先核验，哪些允许入职后补齐？**
4. **什么时候可以创建正式 HR03 人员事实？**
5. **什么时候可以占用 HR02 岗位额度？**
6. **什么时候可以发工号、开账号、开工资、开放门禁？**
7. **各部门任务失败时，入职是否允许继续、如何补偿？**
8. **试用期结束后，转正结论是否形成新的正式人事事实？**

因此禁止以下低质量实现：

- `Candidate.hired=True` 就进入入职；
- Candidate 一进入 onboarding 就直接创建 Employee；
- Portal 填完资料即自动创建账号；
- 报到登记、正式任职、账号开通、发薪起算全部混成一个按钮；
- 缺少 HR04 handoff 来源校验；
- 组织/岗位未确认就先创建正式 Assignment；
- Position Reservation 未提交就算“占岗成功”；
- 工号只用“当前最大值+1”无并发保护；
- 通过手机号/email 自动判断 Person 且直接合并；
- 身份证、银行卡、健康材料进入普通员工列表；
- 所有材料都要求 Day 1 前完成，导致流程僵死；
- 所有材料都允许事后补，导致合规失控；
- 一个“已完成”状态无法解释哪个环节还欠账；
- IT/财务/学院任务只存在备注，没有责任人、截止日和状态；
- 多部门协同失败后静默跳过；
- 账号开通失败但入职显示“完成”；
- 工资档案未就绪但 HR01 显示“已完成入职”；
- 将试用期结束日期直接写 Candidate.probation_end；
- 转正失败直接 `Employee.is_active=False`，无正式人事事件；
- 延期报到直接覆盖原预计日期，不保留历史；
- 放弃入职后 Position Reservation 不释放；
- 同一个 HR04 ProposedHire 重复创建两份 onboarding case；
- Portal token 永久有效；
- Portal token 写入日志；
- 公共 onboarding URL 可枚举；
- Portal 与正式员工账号混为一个身份体系；
- 多学校之间通过手机号/身份证自动识别同一人；
- 导入历史新教工同步逐行保存；
- 未记录“谁核验了哪份材料、依据什么”；
- 试用/转正只做一个是否通过字段；
- 为了 UI 好看伪造“100% 完成”。

---

# 1. 三家成熟 HCM 对标：共同精华

## 1.1 Workday Onboarding Plans：Pre-Hire → Worker 的阶段化体验

Workday 的核心思路不是简单 checklist，而是：

- 支持 Pre-Hire / New Hire；
- Day 1 前即可开始 preboarding；
- Onboarding Plan 按阶段呈现内容和任务；
- 可把任务分散到不同时间，避免首日一次塞满；
- 安全、业务流程和 downstream impact 作为配置前提；
- onboarding 计划与 Core HCM 同一事实体系衔接；
- 管理员有集中 Planner，而新员工看到个性化计划。

跃科吸收：

```text
Pre-Onboarding
Day 0 / Day 1
Week 1
Month 1
Probation
```

任务必须有 `available_from` / `due_at` / `blocking_level`，而不是所有任务从一开始都同时出现。

## 1.2 SAP SuccessFactors Onboarding：角色化任务 + 数据复核 + Recruiting/Core HR 映射

SAP Onboarding 的共同价值：

- 新员工、Hiring Manager、HR、IT 等各自有任务；
- New Hire Data Review 是正式步骤；
- Personal Data Collection 与任务可以并行/按流程变体配置；
- Recruiting 到 Employee Central 有显式 Recruit-to-Hire mapping；
- Onboarding 可在员工开始前启动；
- 文档、数字表单和任务统一；
- Role-Based Permission 控制各角色；
- onboarding、crossboarding、offboarding 使用统一 transition 思路。

跃科吸收：

> **HR04 数据必须先进入 HR05 staging/review，不允许“字段映射后直接写 HR03 权威表”。**

## 1.3 Oracle Journeys：可复用 Journey Template + 条件化任务

Oracle Journeys 的核心精华：

- Onboarding 是 Journey；
- Journey Template；
- 每个 Journey 有多个 task；
- 可以按角色/地点/需求个性化；
- 工作流可被事件触发；
- onboarding 不只是 HR 的任务，还包含员工体验、引导和协同；
- Journey 可有保留/归档策略。

跃科吸收：

```text
OnboardingTemplate
→ OnboardingCase
→ TaskDefinition
→ TaskInstance
```

模板不能直接成为业务事实，必须实例化并冻结版本。

## 1.4 三家共同精华冻结

HR05 必须：

1. Preboarding 和正式生效分开；
2. 新教工自助和管理员处理分开；
3. 入职模板可按人员类别/岗位/学院配置；
4. 每项任务有负责人、截止时间、阻断等级；
5. HR04 → HR05 → HR03 显式映射；
6. 正式数据先 Review 再生效；
7. 入职任务可以并行，但正式闸门按依赖图判断；
8. Portal 体验 mobile-first；
9. 各角色只看到必要数据；
10. 入职后试用/转正形成后续生命周期事件。

---

# 2. 中国高校入职业务校正

高校入职比普通企业 onboarding 更强调：

- 招聘/拟录用来源；
- 人事档案；
- 学历学位核验；
- 工作经历/原单位关系解除；
- 合同/聘用手续；
- 工号；
- 人事系统；
- 统一身份认证；
- 校园卡/门禁；
- 工资与社保；
- 学院报到；
- 党组织/工会等协同；
- 教师资格/教学身份；
- 高层次人才协议；
- 试用/转正。

高校公开办事流程已普遍呈现：

```text
线上信息采集
→ 人事审核
→ 报到
→ 工号/统一身份
→ 校园卡
→ 合同
→ 财务/工资
→ 校内部门协同
```

因此 HR05 必须支持：

```text
人员类别差异
+ 来源差异
+ 材料差异
+ 多部门协同
+ 线上/线下混合办理
```

不能假设所有人只有一个相同模板。

---

# 3. Horilla 2.0 Onboarding 现状审计与 ADAPT 判定

## 3.1 高价值可复用

当前 Horilla 已有：

- `OnboardingStage`
- 按 Recruitment 配阶段；
- stage managers；
- sequence；
- final stage；
- `OnboardingTask`
- task managers；
- candidate assignment；
- required task；
- `CandidateStage`
- 当前阶段；
- required task blocker；
- `CandidateTask`
- `todo/scheduled/ongoing/stuck/done`
- task history；
- `OnboardingPortal`
- token；
- profile；
- onboarding pipeline / kanban；
- candidate list；
- stage drag/drop；
- task bulk update；
- onboarding dashboard；
- offer status；
- candidate mail；
- employee creation / bank detail 页面链。

这些是 HR05 保持 **ADAPT** 的核心基础。

## 3.2 核心缺陷

### 缺陷 A：阶段绑 Recruitment

`OnboardingStage.recruitment_id`

意味着 onboarding template 不是独立产品对象。

高校需要：

```text
教师入职模板
行政人员入职模板
辅导员入职模板
外籍人员入职模板
高层次人才模板
编外人员模板
历史迁移模板
```

这些不能每个 Recruitment 都重新建。

### 缺陷 B：CandidateStage 只有一个当前阶段

它适合作为 Kanban projection，不适合作为正式阶段历史。

新增：

```text
HrOnboardingStageTransition
```

### 缺陷 C：Task status 太粗

现有：

```text
todo
scheduled
ongoing
stuck
done
```

保留 UI 语义，但权威状态至少：

```text
NOT_STARTED
READY
IN_PROGRESS
WAITING_EXTERNAL
BLOCKED
COMPLETED
WAIVED
FAILED
CANCELLED
```

### 缺陷 D：Portal token 过于简单

当前只有：

```text
token
used
count
```

终极版必须：

- token hash 存储；
- 明文只签发一次；
- expiry；
- purpose；
- rotation；
- revoked_at；
- last_used_at；
- attempt/rate limit；
- session binding；
- 无日志明文；
- 不以 token 本身作为用户长期身份。

### 缺陷 E：Candidate → Employee 耦合太早

现有 onboarding 路由存在：

```text
user-creation/<token>
employee-creation/<token>
employee-bank-details/<token>
```

这对 Horilla 企业场景可用，但高校权威模型下必须重构。

最终：

```text
Portal Profile
      ↓
Staging Data
      ↓
Human Verification
      ↓
Activation Command
      ↓
HR03 Authority
      ↓
Legacy Employee Projection
```

而不是 Portal 直接 `Employee.save()`。

### 缺陷 F：正式入职没有事务闸门

缺少：

- HR04 handoff id；
- Position reservation；
- actual report date；
- material verification；
- person match；
- StaffMaster create；
- Assignment；
- account provisioning；
- compensation readiness；
- partial activation / compensation rollback。

## 3.3 Horilla 接管矩阵

| Horilla | HR05 | 处理 |
|---|---|---|
| OnboardingStage | HrOnboardingTemplateStage + projection | ADAPT |
| OnboardingTask | HrOnboardingTaskDefinition | ADAPT |
| CandidateStage | HrOnboardingCase.current_stage projection | LEGACY_PROJECTION |
| CandidateTask | HrOnboardingTaskInstance | ADAPT |
| OnboardingPortal | HrPrehirePortalAccess | REWRITE security |
| onboarding Kanban | Case Stage 工作台 | KEEP/ADAPT |
| onboarding dashboard | HR05 工作台 | ADAPT |
| Candidate | HR04 Application source | 不再作为 HR05 authority |
| Employee creation route | HR03 Activation Service | REWRITE |
| bank detail route | staging + HR15/HR03 controlled data | REWRITE |
| offer status | HR04 authority | 只读 projection |
| email/notify | 通知基础 | KEEP/ADAPT |

---

# 4. HR05 信息架构冻结

```text
HR05 入职管理
├─ HR05-01 待报到人员
├─ HR05-02 报到登记
├─ HR05-03 入职材料核验
├─ HR05-04 入职协同任务
└─ HR05-05 试用与转正
```

五个三级模块冻结，不再增加同层菜单。

## 4.1 五个模块职责

- HR05-01：人还没正式到校，管“是否来、什么时候来、准备到什么程度”；
- HR05-02：人正式报到，管“当天发生什么、哪些权威事实可以生效”；
- HR05-03：管“证据是否真实完整，哪些缺失阻断正式生效”；
- HR05-04：管“学校内部各部门如何把人真正接入运行体系”；
- HR05-05：管“试用期是否合格、是否转正以及如何形成正式事件”。

---

# 5. 角色与数据范围

角色：

```text
HR_ONBOARDING_ADMIN
HR_ONBOARDING_DIRECTOR
COLLEGE_HR
MATERIAL_VERIFIER
IT_PROVISIONER
FINANCE_PROVISIONER
ASSET_PROVISIONER
ACADEMIC_PROVISIONER
TASK_ASSIGNEE
AUDITOR
PREHIRE
```

Data Scope：

```text
SCHOOL
COLLEGE
ORGANIZATION
ONBOARDING_TEMPLATE
ONBOARDING_CASE
ASSIGNED_TASKS
SELF
```

权限：

```text
hr05.case.view
hr05.case.create
hr05.case.cancel
hr05.case.activate

hr05.report.checkin
hr05.material.review
hr05.material.sensitive_view

hr05.task.manage
hr05.task.complete
hr05.task.waive

hr05.identity.provision
hr05.position.commit
hr05.probation.manage
hr05.probation.finalize

hr05.export
hr05.sensitive_export
```

原则：

> 一个 IT 任务执行人可以看到“为工号 20260123 开通邮箱”，但没有理由看到身份证、体检、薪资或完整简历。

---

# 6. 权威领域模型总览

```text
HrOnboardingTemplate
  ├─ HrOnboardingTemplateVersion
  │    ├─ HrOnboardingStageDefinition
  │    └─ HrOnboardingTaskDefinition
  │
  └─ HrOnboardingCase
       ├─ HrPrehireProfile
       ├─ HrReportAppointment[]
       ├─ HrReportCheckin
       ├─ HrOnboardingMaterial[]
       ├─ HrMaterialVerification[]
       ├─ HrOnboardingTaskInstance[]
       ├─ HrOnboardingStageTransition[]
       ├─ HrActivationAttempt[]
       ├─ HrProvisioningRequest[]
       ├─ HrProbationCase
       └─ HrOnboardingAuditEvent[]
```

---

# 7. HrOnboardingCase

核心：

```text
HrOnboardingCase
- id UUID
- tenant_id
- case_no
- source_type
- source_id
- hr04_proposed_hire_id nullable
- hr04_application_id nullable
- candidate_id nullable
- person_match_status
- planned_organization_id
- planned_post_catalog_id
- planned_position_id nullable
- position_reservation_id nullable
- employment_type
- staff_category
- expected_report_date
- actual_report_at nullable
- status
- current_stage_code
- activation_status
- hr03_person_id nullable
- hr03_staff_master_id nullable
- hr03_employment_id nullable
- hr03_assignment_id nullable
- template_version_id
- version
- created_at
```

`source_type`：

```text
HR04_HIRE
LEGAL_MANUAL_MIGRATION
TRANSFER_IN
POLICY_IMPORT
```

V1 默认禁止无来源创建；人工创建必须有高权限和 reason。

---

# 8. Onboarding Case 权威状态机

```text
CREATED
→ PREPARING
→ READY_TO_REPORT
→ REPORT_SCHEDULED
→ REPORTED
→ VERIFYING
→ READY_FOR_ACTIVATION
→ ACTIVATING
→ ACTIVE
→ ONBOARDING_IN_PROGRESS
→ ONBOARDING_COMPLETED
→ PROBATION
→ CONFIRMED
```

异常：

```text
REPORT_DELAYED
DECLINED
NO_SHOW
BLOCKED
ACTIVATION_FAILED
CANCELLED
PROBATION_EXTENDED
PROBATION_FAILED
```

关键语义：

- `REPORTED`：人确实完成报到动作；
- `ACTIVE`：HR03 正式人员事实和核心资格已成功生效；
- `ONBOARDING_COMPLETED`：跨部门入职任务达到完成规则；
- `CONFIRMED`：试用转正最终完成。

不得把这四个状态合并为一个“完成”。

---

# 9. HR05-01 待报到人员施工卡

## 9.1 业务目标

回答：

- 谁已经录用但还没到校？
- 预计哪天来？
- 哪些人已经确认意愿？
- 哪些材料可提前准备？
- 哪些人延期？
- 哪些 Offer 临近失效？
- 哪些岗位额度长期被占用但人没来？

## 9.2 页面路由

```text
/hr/onboarding/prehires
/hr/onboarding/prehires/:caseId
/hr/onboarding/prehires/:caseId/portal
```

## 9.3 首屏

```text
┌──────────────────────────────────────────────────────────┐
│ 待报到人员                  [新建合法迁移] [导出]         │
│ 2026秋季集中报到 · 当前学校                               │
├──────────────────────────────────────────────────────────┤
│ 待确认 18 │ 已确认 42 │ 7天内报到 25 │ 延期 3 │ 风险 4   │
├──────────────────────────────────────────────────────────┤
│ [全部][待确认][准备中][已预约][延期][No-show][放弃]      │
├──────────────────────────────────────────────────────────┤
│ 姓名 │ 学院 │ 岗位 │ 预计报到 │ 准备度 │ 缺项 │ 状态     │
└──────────────────────────────────────────────────────────┘
```

`准备度` 不是虚假百分比。

可计算：

```text
required_pre_report_tasks_completed / required_pre_report_tasks_total
```

并同时显示阻断项。

## 9.4 Case Detail

头部：

```text
张三
软件工程专任教师
计算机学院
来源：HR04-2026-001
Offer：已接受
预计报到：2026-09-01
岗位预占：有效
```

Tabs：

```text
报到准备
个人资料
材料
岗位与组织
Portal状态
通知
历史
审计
```

## 9.5 入职意愿

状态：

```text
PENDING
CONFIRMED
REQUESTED_DELAY
DECLINED
NO_RESPONSE
```

候选人可以：

- 确认；
- 申请改报到日期；
- 放弃；
- 提交原因。

延期必须走审批/确认，不能直接覆盖原日期。

## 9.6 Portal

Portal 首页：

```text
欢迎加入 XX大学
你的预计报到日
入职准备进度
待完成事项
已完成
联系方式
```

移动优先。

## 9.7 Portal Access 模型

```text
HrPrehirePortalAccess
- id
- tenant_id
- onboarding_case_id
- token_hash
- purpose
- expires_at
- revoked_at
- last_used_at
- failed_attempts
- status
```

明文 token：

- 只在签发时存在；
- 不入数据库；
- 不入日志；
- 不入 URL analytics。

## 9.8 风险

自动风险：

```text
OFFER_EXPIRING
REPORT_DATE_NEAR_NO_CONFIRM
POSITION_RESERVATION_EXPIRING
MISSING_BLOCKING_DOCUMENT
PORTAL_NOT_ACTIVATED
DELAYED_MULTIPLE_TIMES
```

---

# 10. HR05-02 报到登记施工卡

## 10.1 这是 HR05 最关键的事务页

报到登记不是“签到”。

它是：

> **确认这个人已经发生“到校入职事件”，并判断哪些正式人事事实允许在何时生效。**

## 10.2 路由

```text
/hr/onboarding/reporting
/hr/onboarding/cases/:id/report
/hr/onboarding/cases/:id/activation
```

## 10.3 页面布局

```text
┌────────────────────────────────────────────────────────────┐
│ 张三 · 入职报到                        当前：READY_TO_REPORT │
│ 招聘来源：HR04-2026-001   预计报到：09-01                  │
├────────────────┬───────────────────────┬───────────────────┤
│ 报到事实        │ 组织/岗位与聘用        │ 生效前闸门          │
│                │                       │                   │
│ 实际到校时间    │ 计算机学院             │ ✓ HR04录用有效      │
│ 身份核验        │ 专任教师               │ ✓ 岗位预占有效      │
│ 报到地点        │ Position P-001        │ ✓ 身份材料           │
│ 经办人          │ 用工性质：事业编       │ ! 合同待签           │
│                │                       │ ✓ 学历核验           │
├────────────────┴───────────────────────┴───────────────────┤
│ [保存草稿] [确认报到] [执行正式生效]                       │
└────────────────────────────────────────────────────────────┘
```

“确认报到”和“执行正式生效”必须是两个动作。

## 10.4 Report Checkin

```text
HrReportCheckin
- onboarding_case_id
- actual_report_at
- location
- checked_identity
- operator_id
- notes
- source
- version
```

报到确认幂等。

## 10.5 Activation Gate

正式生效必须检查：

```text
HR04 handoff valid
OnboardingCase REPORTED
Person match resolved
RequiredActivationMaterials verified
HR02 position reservation valid
Organization active as-of effective date
Position active
Employment type resolved
Staff category resolved
Employment effective_from valid
Assignment effective_from valid
No duplicate active StaffMaster conflict
```

根据学校配置可追加：

- Contract signed；
- 档案到校；
- 体检合格；
- 无犯罪材料；
- 教师资格等。

## 10.6 正式 Activation

建议一个领域命令：

```text
ActivateOnboardingCase(case_id, effective_at, idempotency_key)
```

事务内：

1. `SELECT ... FOR UPDATE onboarding_case`；
2. 再次检查状态；
3. 检查 HR02 reservation；
4. HR03 `match_or_create_person`；
5. create StaffMaster；
6. create EmploymentRelationship；
7. create primary Assignment；
8. commit HR02 reservation；
9. freeze activation snapshot；
10. emit outbox events；
11. case → ACTIVE。

不要在同一数据库事务里同步等待外部 SSO、邮箱、门禁系统。

## 10.7 外部系统开通

事务成功后 outbox：

```text
StaffActivated
```

消费者：

- Identity/IAM；
- 邮箱；
- OA；
- 一卡通；
- 教务；
- 财务；
- 门禁。

失败：

```text
核心 HR activation 成功
外部 provisioning = PARTIAL_FAILED
```

必须能补偿重试，不能回滚已经真实发生的人事报到事实。

---

# 11. 工号模型

工号是关键身份编号。

禁止：

```text
max(employee_no)+1
```

建议：

```text
HrStaffNumberSequence
- tenant_id
- rule_version
- current_sequence
- prefix
- year_scope
- version
```

分配：

- DB sequence / advisory lock / `select_for_update`；
- tenant-scoped；
- 可预分配；
- 正式生效后 immutable；
- 作废号保留 audit，不回收复用。

工号 ≠ 用户名强制等同。

---

# 12. HR05-03 入职材料核验施工卡

## 12.1 目标

不是文件夹。

系统必须回答：

- 这个岗位/人员类别需要哪些材料？
- 哪些是 Day 1 硬阻断？
- 哪些允许入职后补齐？
- 谁核验？
- 核验的是哪一个文件版本？
- 依据什么？
- 是否过期？
- 是否和 HR04 材料复用？
- 是否要进入 HR03 长期档案？

## 12.2 Material Requirement

```text
HrOnboardingMaterialRequirement
- id
- template_version_id
- material_type
- label
- required
- blocking_phase
- condition_json
- allowed_formats
- max_size
- verification_required
- destination_domain
- retention_policy
```

`blocking_phase`：

```text
PRE_REPORT
REPORT
ACTIVATION
POST_ACTIVATION
PROBATION
```

## 12.3 Material

```text
HrOnboardingMaterial
- id
- tenant_id
- onboarding_case_id
- requirement_id
- source HR04 / PORTAL / HR_UPLOAD / EXTERNAL_VERIFY
- file_version_id
- status
- issue_date
- expiry_date
- submitted_at
```

状态：

```text
MISSING
SUBMITTED
UNDER_REVIEW
RETURNED
VERIFIED
REJECTED
EXPIRED
WAIVED
```

## 12.4 Verification

```text
HrMaterialVerification
- material_id
- verification_type
- result
- reviewer_id
- verified_at
- evidence_snapshot
- reason
```

结果：

```text
VERIFIED
MISMATCH
UNREADABLE
NEEDS_ORIGINAL
NEEDS_EXTERNAL_CHECK
INVALID
```

## 12.5 页面

```text
左：材料目录
中：文件预览
右：要求 / 来源 / 核验动作 / 历史
```

支持：

- 下一项；
- 仅看待核验；
- 缺件；
- 退回；
- 已过期；
- 敏感材料受控显示。

## 12.6 材料复用

HR04 已核验的材料：

```text
reuse_as_evidence
```

但 HR05 不能无条件继承“已验证”状态。

根据 requirement：

```text
TRUST_SOURCE
REVERIFY
REQUIRE_ORIGINAL
```

## 12.7 高敏材料

如：

- 身份证；
- 体检；
- 无犯罪；
- 银行卡；
- 档案内容。

服务端裁剪。

Material reviewer 不等于所有 PII access。

---

# 13. 档案到校与人事档案核验

高校特色，必须明确。

```text
HrPersonnelFileTransfer
- onboarding_case_id
- source_unit
- requested_at
- received_at
- tracking_no
- review_status
- missing_items
- reviewer
```

状态：

```text
NOT_REQUIRED
TO_BE_REQUESTED
REQUESTED
IN_TRANSIT
RECEIVED
UNDER_REVIEW
VERIFIED
ISSUE_FOUND
```

是否阻断 Activation 按学校 policy。

---

# 14. HR05-04 入职协同任务施工卡

## 14.1 目标

这是 HR05 最大的“日常价值”工作区。

新教工到校后需要多个部门完成事项。

正式任务图：

```text
HR Activation
├─ IT：统一身份
├─ IT：邮箱/OA
├─ 卡务：一卡通
├─ 门禁：权限
├─ 财务：工资档案
├─ 财务：银行卡/发薪
├─ 社保：参保
├─ 学院：办公位/导师/报到
├─ 资产：电脑/设备
├─ 图书：读者权限
└─ 教务：教师教学身份
```

## 14.2 Template / Instance

```text
HrOnboardingTaskDefinition
- template_version_id
- code
- title
- category
- responsible_role
- due_offset
- available_offset
- blocking_level
- prerequisite_codes
- completion_type
- automation_handler
- candidate_visible
- sequence

HrOnboardingTaskInstance
- onboarding_case_id
- definition_id
- assignee_type
- assignee_id
- status
- available_at
- due_at
- started_at
- completed_at
- completion_payload
- failure_code
- version
```

## 14.3 blocking level

```text
INFO
NON_BLOCKING
BLOCKS_ACTIVATION
BLOCKS_ONBOARDING_COMPLETE
BLOCKS_PAYROLL
BLOCKS_WORK_ACCESS
```

不能只有 `is_required=True/False`。

## 14.4 Task 状态

```text
NOT_STARTED
READY
IN_PROGRESS
WAITING_EXTERNAL
BLOCKED
FAILED
COMPLETED
WAIVED
CANCELLED
```

`WAIVED` 必须：

- reason；
- authority；
- audit；
- 不等同于 COMPLETED。

## 14.5 页面布局

```text
┌───────────────────────────────────────────────────────────┐
│ 入职协同中心           本周入职 25   超期 8   阻塞 3      │
├────────────┬──────────────────────────────────────────────┤
│ 按部门      │ 任务矩阵                                     │
│ HR          │ 姓名 | 工号 | 邮箱 | OA | 一卡通 | 工资 | ... │
│ IT          │                                               │
│ 财务        │                                               │
│ 学院        │                                               │
└────────────┴──────────────────────────────────────────────┘
```

另有“我的任务”视图：

```text
待办
进行中
等待外部
超期
已完成
```

## 14.6 责任人解析

不要把 template 直接保存具体 Employee ID。

用：

```text
RESPONSIBLE_HR
COLLEGE_HR
HIRING_MANAGER
IT_SERVICE
FINANCE_SERVICE
ACADEMIC_SERVICE
CUSTOM_GROUP
```

实例化时解析到实际 assignee。

## 14.7 自动化任务

例如：

```text
CREATE_SSO_ACCOUNT
CREATE_EMAIL
SYNC_TEACHER_IDENTITY
CREATE_PAYROLL_PROFILE
```

必须：

```text
PENDING
→ RUNNING
→ SUCCESS / FAILED
```

并有 retry/dead-letter。

不能把“HTTP 返回 200”直接等于业务成功；要接受 external reference / reconciliation。

## 14.8 手工任务

必须：

- 完成人；
- 时间；
- 备注；
- 证据；
- 审计。

---

# 15. Provisioning Request

外部系统开通统一抽象：

```text
HrProvisioningRequest
- id
- tenant_id
- onboarding_case_id
- target_system
- operation
- idempotency_key
- payload_version
- status
- external_ref
- attempt_count
- next_retry_at
- last_error
- completed_at
```

状态：

```text
PENDING
RUNNING
SUCCESS
FAILED_RETRYABLE
FAILED_TERMINAL
CANCELLED
```

必须 reconciliation。

---

# 16. 正式入职完成定义

“入职完成”不是所有任务全绿。

定义配置：

```text
OnboardingCompletionPolicy
```

至少：

```text
case ACTIVE
AND all BLOCKS_ONBOARDING_COMPLETE tasks completed/waived
AND no unresolved critical risk
```

非阻断任务可继续后置。

UI：

```text
正式生效：已完成
入职协同：87%
阻断项：0
后续事项：3
```

不误导用户。

---

# 17. HR05-05 试用与转正施工卡

## 17.1 目标

将 Horilla 的 `probation_end` 单日期升级成正式人事事件。

高校试用期可能适用于不同用工类型，学校规则不同。

## 17.2 模型

```text
HrProbationCase
- id
- tenant_id
- staff_master_id
- employment_relationship_id
- onboarding_case_id
- start_date
- planned_end_date
- actual_end_date
- policy_version_id
- status
- result
- extension_count
- version
```

状态：

```text
NOT_STARTED
IN_PROGRESS
REVIEW_DUE
UNDER_REVIEW
EXTENDED
CONFIRMED
FAILED
CANCELLED
```

## 17.3 目标

```text
HrProbationGoal
- probation_case_id
- category
- title
- description
- evaluator_role
- evidence_required
```

可按：

- 教师；
- 管理；
- 辅导员；
- 其他专技。

配置不同模板。

## 17.4 评价流程

```text
员工自评
→ 单位评价
→ 人事审核
→ 学校确认（若需）
```

允许：

```text
CONFIRM
EXTEND
FAIL
```

## 17.5 延长

延长不是修改 planned_end_date。

创建：

```text
HrProbationExtension
- old_end_date
- new_end_date
- reason
- approval
```

保留历史。

## 17.6 转正事实

转正成功：

- probation case `CONFIRMED`；
- 发出 `ProbationConfirmed`；
- 更新 EmploymentRelationship/相关状态（按 HR03 领域服务）；
- 不直接改多个表。

失败：

- 发出人事处理事件；
- 由 HR07/HR16 等后续域处理合同/离开；
- HR05 不直接删除员工。

## 17.7 页面

首屏：

```text
试用中 56
30天到期 13
待评价 9
延期 2
异常 1
```

列表：

- 姓名；
- 学院；
- 岗位；
- 入职日；
- 计划转正日；
- 评价进度；
- 状态；
- 风险。

详情：

```text
基本事实
试用目标
员工自评
学院评价
审核
材料
转正结果
历史
```

---

# 18. Onboarding Template

模板必须独立于 Recruitment。

```text
HrOnboardingTemplate
- tenant_id
- code
- name
- applicable_staff_categories
- applicable_employment_types
- applicable_post_categories
- applicable_organizations
- status

HrOnboardingTemplateVersion
- template_id
- version_no
- effective_from
- effective_to
- status DRAFT / ACTIVE / RETIRED
- snapshot_json
```

Case 创建时绑定 version。

后面改模板不影响旧 Case。

---

# 19. Template 选择规则

优先级：

```text
人员类别+用工性质+岗位类别+组织精确匹配
→ 人员类别+岗位类别
→ 人员类别
→ 默认模板
```

若多个同优先级匹配：

```text
CONFIGURATION_CONFLICT
```

禁止随机取 `.first()`。

---

# 20. Prehire Profile

Portal 采集数据先进入 staging：

```text
HrPrehireProfile
- onboarding_case_id
- legal_name
- contact
- address
- emergency_contact
- education draft
- work_experience draft
- bank draft
- tax/social-insurance draft
- other onboarding fields
- submitted_at
- verification_status
```

禁止直接写 HR03 权威表。

---

# 21. Recruit-to-Hire Mapping

必须生成：

```text
docs/hr05/RecruitToHireMapping.md
```

至少：

```text
HR04 Candidate/Application Field
→ HR05 Staging Field
→ HR03 Authority Field
→ Transform
→ Required?
→ Reviewer
→ Conflict Policy
```

例如：

```text
Application.legal_name
→ PrehireProfile.legal_name
→ HrPerson.legal_name

RecruitmentPosition.organization
→ OnboardingCase.planned_organization
→ HrAssignment.organization

Offer.employment_type
→ OnboardingCase.employment_type
→ EmploymentRelationship.type
```

不能“字段名一样就自动映射”。

---

# 22. 数据冲突

例如 Portal 填：

```text
学历 = 博士
```

HR04 已验证：

```text
学历 = 硕士
```

不能静默覆盖。

生成：

```text
HrOnboardingDataConflict
- field
- source_a
- source_b
- values
- resolution
- resolved_by
```

阻断级别配置。

---

# 23. Person Match

在 Activation 前：

```text
EXACT_MATCH
POSSIBLE_MATCH
NO_MATCH
INSUFFICIENT_DATA
```

tenant-private。

禁止跨学校 Person 自动合并。

不允许只凭 email 自动匹配。

---

# 24. HR02 Position 事务

Case 创建：

```text
HR04 reservation 继承
```

报到延期：

- reservation 可续期；
- 超期需要审批/重新验证。

Activation：

```text
HELD → COMMITTED
```

放弃/No-show/取消：

```text
HELD → RELEASED
```

失败必须有补偿作业。

---

# 25. HR03 Activation Snapshot

正式生效后保存：

```text
HrOnboardingActivationSnapshot
- onboarding_case_id
- activated_at
- person_id
- staff_master_id
- employment_id
- assignment_id
- staff_no
- organization_id
- position_id
- source_versions_json
```

以后审计可回答：

> “这个人 2026-09-01 入职时是按照哪些来源数据创建的？”

---

# 26. 账号/SSO 生效边界

账号不是 Employee.save() 副作用。

必须独立 provisioning。

建议：

```text
StaffActivated
→ IAM consumer
→ AccountProvisioned
```

若 IAM 失败：

- 人事事实仍可 ACTIVE；
- 工作访问状态 `PARTIAL`；
- HR01/HR05 出风险；
- 自动重试；
- 人工补救。

根据学校政策也可把 IAM 设为 `BLOCKS_WORK_ACCESS`，但不要回滚实际报到事实。

---

# 27. 银行与工资边界

HR05 只负责：

- 采集；
- 核验基础字段；
- 发出 PayrollProfileRequested。

HR15 负责正式工资计算/工资档案。

银行卡为高敏：

- 字段加密；
- 仅授权财务/本人；
- 列表默认遮罩；
- 导出受控；
- 访问审计。

---

# 28. 合同边界

HR07 是合同权威域。

HR05：

- 显示合同前置；
- 发起合同签订任务；
- 读取合同状态；
- 根据学校 policy 判断是否 BLOCKS_ACTIVATION。

不得在 HR05 自建第二份权威合同。

---

# 29. 教师教学身份边界

正式 StaffActivated 后：

```text
AcademicTeacherIdentityRequested
```

由数字校园/教务集成处理。

失败：

- HR 主档不回滚；
- 教务身份任务失败；
- HR05 协同中心显示。

---

# 30. 公共 UI 体系

继承 HR01–HR04。

新增公共组件：

```text
HrOnboardingCaseHeader
HrOnboardingReadinessCard
HrPrehireStatusBadge
HrReportStatusBadge
HrActivationGate
HrActivationChecklist
HrOnboardingProgress
HrStageRail
HrTaskMatrix
HrTaskStatusBadge
HrBlockingLevelBadge
HrTaskOwnerAvatar
HrProvisioningStatus
HrMaterialChecklist
HrMaterialVerificationPanel
HrDataConflictBanner
HrPersonMatchPanel
HrPositionReservationCard
HrPortalSecurityStatus
HrProbationTimeline
HrProbationDecisionBar
```

---

# 31. 顶级 UI 原则

HR05 是很适合“卖看相”的模块，但视觉必须服务业务判断。

## 31.1 待报到页面

首屏先回答：

```text
谁快来了？
谁还没确认？
谁缺材料？
谁占着岗位但延期？
```

## 31.2 报到页面

不是超长表单。

使用：

```text
左：报到事实
中：组织/岗位/身份
右：Activation Gate
```

## 31.3 材料核验

采用三栏证据工作台。

## 31.4 协同中心

采用矩阵/任务视图，不做 20 个卡片堆叠。

## 31.5 Portal

375px 优先：

```text
欢迎
时间线
下一步
资料
材料
帮助
```

不要把后台表格缩成手机版。

## 31.6 试用转正

使用阶段时间线和评价分区。

---

# 32. 后端结构

建议：

```text
hr_onboarding/
    models/
        template.py
        case.py
        prehire.py
        material.py
        reporting.py
        activation.py
        task.py
        provisioning.py
        probation.py
    services/
        case_service.py
        report_service.py
        material_service.py
        activation_service.py
        task_service.py
        provisioning_service.py
        probation_service.py
    selectors/
    policies/
    api/
    portal/
    integrations/
        hr02.py
        hr03.py
        hr04.py
        hr07.py
        hr15.py
        iam.py
        academic.py
    projections/
        horilla_onboarding.py
    jobs/
    tests/
```

旧 `onboarding/` 保持运行，逐步成为 legacy adapter/projection。

---

# 33. API 总合同

基路径：

```text
/api/hr/v1/onboarding/*
```

所有 response：

```json
{
  "apiVersion": "v1",
  "schemaVersion": "hr05.1",
  "requestId": "uuid",
  "data": {}
}
```

V1：

- additive-only；
- enum 新值 graceful fallback；
- breaking change `/v2/`。

写操作：

```text
Idempotency-Key
If-Match/version
```

---

# 34. 核心 API

```http
GET  /api/hr/v1/onboarding/cases
GET  /api/hr/v1/onboarding/cases/{id}

POST /api/hr/v1/onboarding/cases/{id}/confirm-intent
POST /api/hr/v1/onboarding/cases/{id}/request-delay
POST /api/hr/v1/onboarding/cases/{id}/decline

POST /api/hr/v1/onboarding/cases/{id}/report
GET  /api/hr/v1/onboarding/cases/{id}/activation-gate
POST /api/hr/v1/onboarding/cases/{id}/activate

GET  /api/hr/v1/onboarding/cases/{id}/materials
POST /api/hr/v1/onboarding/materials/{id}/verify
POST /api/hr/v1/onboarding/materials/{id}/return

GET  /api/hr/v1/onboarding/cases/{id}/tasks
POST /api/hr/v1/onboarding/tasks/{id}/start
POST /api/hr/v1/onboarding/tasks/{id}/complete
POST /api/hr/v1/onboarding/tasks/{id}/waive

GET  /api/hr/v1/onboarding/probations
POST /api/hr/v1/onboarding/probations/{id}/submit-review
POST /api/hr/v1/onboarding/probations/{id}/confirm
POST /api/hr/v1/onboarding/probations/{id}/extend
POST /api/hr/v1/onboarding/probations/{id}/fail
```

Portal：

```http
GET  /api/hr/v1/prehire/me
PATCH /api/hr/v1/prehire/me/profile
POST /api/hr/v1/prehire/me/materials
POST /api/hr/v1/prehire/me/confirm-intent
```

Portal 不接受任意 case id。

---

# 35. 错误码

```text
ONBOARDING_CASE_INVALID_SOURCE
ONBOARDING_CASE_DUPLICATE
INVALID_STATE_TRANSITION
POSITION_RESERVATION_INVALID
PERSON_MATCH_REQUIRED
PERSON_MATCH_CONFLICT
BLOCKING_MATERIAL_MISSING
MATERIAL_NOT_VERIFIED
ACTIVATION_ALREADY_COMPLETED
ACTIVATION_PARTIAL_FAILURE
STAFF_NUMBER_CONFLICT
TASK_PREREQUISITE_NOT_MET
TASK_ALREADY_COMPLETED
PORTAL_TOKEN_EXPIRED
PORTAL_TOKEN_REVOKED
PROBATION_ALREADY_FINALIZED
VERSION_CONFLICT
```

---

# 36. 任务 DAG

任务不是只靠 Stage 顺序。

支持依赖：

```text
Identity Verified
      ↓
Staff Activated
      ├─ SSO
      ├─ Email
      ├─ Payroll
      └─ Campus Card
             ↓
        Access Ready
```

Definition：

```text
prerequisite_task_codes
```

必须防环。

---

# 37. 阶段与任务分离

Stage 是用户理解：

```text
报到前准备
正式报到
系统开通
部门接入
试用期
```

Task 才是实际工作。

不能通过拖 Stage 卡片绕过 task gate。

移动 Stage：

- 调用 transition service；
- 检查 blocking tasks；
- 记录 transition；
- projection 更新。

---

# 38. 通知

事件：

```text
ONBOARDING_CREATED
PORTAL_INVITED
REPORT_REMINDER
REPORT_DELAY_APPROVED
MATERIAL_RETURNED
MATERIAL_VERIFIED
READY_FOR_ACTIVATION
STAFF_ACTIVATED
PROVISIONING_FAILED
TASK_ASSIGNED
TASK_OVERDUE
ONBOARDING_COMPLETED
PROBATION_DUE
PROBATION_CONFIRMED
```

通知必须去重、模板版本化、可重试。

---

# 39. 数据新鲜度

HR01/HR05 Dashboard：

```text
sourceUpdatedAt
calculatedAt
maxStaleSeconds
hardExpireSeconds
status
```

Task/Provisioning 状态属于操作事实：

- 关键详情尽量实时；
- dashboard 可短 TTL；
- Activation Gate 禁止使用过期缓存。

---

# 40. 敏感数据

分级：

```text
NORMAL
INTERNAL
SENSITIVE
HIGH_SENSITIVE
```

HIGH：

- 身份证；
- 银行卡；
- 健康；
- 无犯罪；
- 部分档案；
- 家庭信息。

字段级权限 + access audit。

---

# 41. 文件安全

沿用 HR03/HR04：

- private storage；
- signed URL；
- MIME；
- extension；
- double extension；
- malware scan；
- SHA-256；
- version；
- download audit；
- no direct media path。

---

# 42. Excel

可用：

- 历史入职案例迁移；
- 报到人员名单；
- 多部门任务批量导入/分配；
- 历史转正结果。

流程：

```text
template
→ upload
→ staging
→ validation
→ error workbook
→ confirm
→ async
→ result
→ audit
```

禁止 Excel 直接绕过 Activation Service。

---

# 43. Legacy Mapping

必须生成：

```text
docs/hr05/LegacyOnboardingMapping.md
```

最低：

| Horilla | HR05 | 策略 |
|---|---|---|
| OnboardingStage | TemplateStage | ADAPT |
| OnboardingTask | TaskDefinition | ADAPT |
| CandidateStage | Case.current_stage | projection |
| CandidateTask | TaskInstance | migrate |
| OnboardingPortal | PrehirePortalAccess | security rewrite |
| Candidate.hired/start_onboard | HR04 handoff | deprecated authority |
| Candidate.joining_date | Onboarding expected/report date | migrate |
| Candidate.probation_end | ProbationCase | rewrite |
| employee_creation(token) | ActivationService | remove authority |
| bank details portal | staging/HR15 | rewrite |
| Kanban | Case stage UI | keep/adapt |

---

# 44. Legacy 退出合同

模式：

```text
LEGACY_ONBOARDING_ONLY
→ DUAL_READ_COMPARE
→ HR05_AUTHORITY
```

进入 HR05_AUTHORITY 后：

- 新 Case 只写 HR05；
- Horilla CandidateStage/CandidateTask 为 projection；
- Portal 不再创建 Employee；
- 不自动 fallback legacy；
- 回滚必须 runbook。

---

# 45. DUAL_READ_COMPARE

对账：

```text
candidate count
current stage
required tasks
task status
joining date
portal status
probation end
```

输出 discrepancy。

不允许：

```text
新系统空就读旧系统
```

---

# 46. 数据迁移

Migration 过程：

1. Recruitment/Candidate 对应到 HR04/HR05；
2. 创建 OnboardingCase；
3. 映射 current stage；
4. 迁移 task；
5. 迁移 joining/probation；
6. 识别已转换 Employee；
7. 回填 HR03 link；
8. 生成 activation snapshot；
9. 对账。

历史已经入职的人：

```text
source_type = LEGACY_MIGRATION
```

不得重新触发账号/岗位等副作用。

---

# 47. 并发与事务

必须测试：

## 同一 HR04 handoff 重复消费

unique source id + idempotency。

## 两个 HR 同时 Activate

case row lock + version。

## 工号并发

sequence lock。

## Position reservation

事务 commit。

## Portal 重复提交

idempotency。

## Task 双完成

version conflict/idempotency。

## 转正双审批

final state lock。

---

# 48. Outbox

事件：

```text
OnboardingCaseCreated
PrehireConfirmed
EmployeeReported
StaffActivated
ProvisioningRequested
ProvisioningSucceeded
ProvisioningFailed
OnboardingCompleted
ProbationReviewDue
ProbationConfirmed
ProbationFailed
```

transactional outbox。

---

# 49. 可观测性

metrics：

```text
hr05_cases_waiting_report
hr05_report_delayed_total
hr05_activation_failed_total
hr05_activation_duration_seconds
hr05_material_pending_total
hr05_task_overdue_total
hr05_provisioning_failed_total
hr05_probation_due_total
hr05_legacy_discrepancy_total
```

日志：

```text
requestId
tenant
case_id
staff_no (可按政策)
action
duration
error_code
```

禁止 PII 明文。

---

# 50. 数据质量

检查：

```text
Case 无合法 source
HR04 source 重复 Case
REPORTED 无 actual_report_at
ACTIVE 无 HR03 person/staff/employment/assignment
ACTIVE position reservation 未 commit
COMPLETED 有 blocking task 未完成
Task completed 无 completion actor
Provisioning success 无 external_ref
Probation confirmed 无 decision
Portal token 过期但仍可访问
```

---

# 51. 性能目标

建议：

- Case list p95 < 500ms；
- Case detail p95 < 700ms；
- Activation Gate p95 < 800ms；
- Material list p95 < 700ms；
- Task matrix 500 cases p95 < 1s；
- Portal 首页 p95 < 800ms；
- Activation 核心 DB transaction < 1.5s（不等外部系统）；
- 大导出异步；
- Dashboard 禁止 N+1。

---

# 52. 安全测试矩阵

必须：

- A 校看不到 B 校；
- 学院 A 看不到学院 B；
- PREHIRE 只看本人；
- Portal token expiry；
- revoked token；
- token brute-force；
- IDOR；
- Material URL 越权；
- 银行卡遮罩；
- 高敏下载 audit；
- Task assignee 不能读不必要 PII；
- IT provider 不能看体检；
- Activation permission；
- Probation finalize permission；
- Excel export scope；
- malicious upload；
- XSS；
- CSRF；
- rate limit。

---

# 53. HR05-01 验收

- HR04 handoff 自动建 Case；
- 重复 handoff 不重复；
- Portal invite；
- 确认意愿；
- 延期；
- 放弃；
- reservation release；
- 风险；
- scope；
- mobile portal；
- audit。

---

# 54. HR05-02 验收

- 报到确认；
- 报到幂等；
- Gate 正确；
- Person match；
- 工号并发；
- HR03 create；
- HR02 commit；
- Assignment effective date；
- outbox；
- 外部 provisioning 失败不破坏核心人事事实；
- activation 重复调用返回原结果。

---

# 55. HR05-03 验收

- requirement template；
- blocking phase；
- 上传；
- 退回；
- 重新提交；
- 核验；
- HR04 material reuse；
- reverify；
- sensitive；
- personnel file；
- audit。

---

# 56. HR05-04 验收

- template→instances；
- responsibility resolve；
- prerequisite；
- block level；
- manual completion；
- automated job；
- retry；
- failed；
- overdue；
- waive；
- task matrix；
- onboarding completion policy。

---

# 57. HR05-05 验收

- 创建 probation；
- 到期提醒；
- self-review；
- college review；
- HR finalize；
- extend；
- confirm；
- fail；
- history；
- HR03 event；
- 终局后不能直接改。

---

# 58. 前端 E2E

必须覆盖：

1. HR04 Offer accepted；
2. HR05 case 创建；
3. 新教工手机打开 Portal；
4. 确认意愿；
5. 填资料；
6. 上传材料；
7. HR 退回；
8. 补材料；
9. 预约报到；
10. 报到；
11. Activation Gate；
12. 激活；
13. SSO task；
14. 财务 task；
15. 学院 task；
16. provisioning failure；
17. retry；
18. onboarding completed；
19. probation due；
20. confirmed。

---

# 59. 视觉回归

截图：

- 待报到列表；
- Prehire detail；
- Portal；
- 报到登记；
- Activation Gate；
- Material verification；
- Task matrix；
- Provisioning failure；
- Probation list；
- Probation detail；
- empty/error/partial/permission/stale。

视口：

```text
1440
1280
768
375
```

---

# 60. Accessibility

- Portal 键盘完成；
- 表单 error；
- progress 不只靠颜色；
- Task Matrix 可键盘操作；
- focus visible；
- screen reader label；
- mobile 不爆版；
- dialog focus trap；
- 文件有替代操作；
- 日期有清晰 label。

---

# 61. API Contract Tests

必须：

- apiVersion；
- schemaVersion；
- requestId；
- pagination；
- error envelope；
- If-Match；
- idempotency；
- enum fallback；
- additive compatibility。

---

# 62. 数据库约束

至少：

- source_type + source_id tenant unique；
- case_no tenant unique；
- staff_no tenant unique；
- one active probation per employment；
- task instance unique by case+definition+cycle；
- portal access active token unique；
- activation snapshot one per successful activation；
- FKs tenant consistent；
- counts nonnegative；
- version >= 1。

---

# 63. 索引

```text
(tenant_id, status)
(tenant_id, expected_report_date)
(tenant_id, actual_report_at)
(tenant_id, planned_organization_id, status)
(tenant_id, current_stage_code)
(onboarding_case_id, status)
(assignee_id, status, due_at)
(staff_master_id, status)
```

---

# 64. 列表查询规范

所有正式列表：

```text
WHERE
→ COUNT
→ ORDER
→ PAGE
```

禁止 Python 后过滤。

Task Matrix 可按时间窗口预聚合。

---

# 65. 配置边界

可配置：

- onboarding template；
- stage；
- task；
- due offset；
- blocking level；
- material requirement；
- activation policy；
- personnel-file policy；
- probation policy；
- notification。

不可配置掉：

- tenant isolation；
- source idempotency；
- HR02 capacity；
- HR03 activation service；
- audit；
- sensitive controls；
- token security；
- version；
- task completion evidence；
- activation snapshot。

---

# 66. 自纠错与遗漏检查

## 66.1 报到 vs 正式生效

已拆分。

## 66.2 正式生效 vs 外部账号成功

已拆分。

## 66.3 入职完成 vs 试用转正

已拆分。

## 66.4 Candidate 不是 StaffMaster

已处理。

## 66.5 Portal 不直接写 HR03

已处理。

## 66.6 Portal Token 安全

已升级 hash/expiry/revoke。

## 66.7 Position 超卖

接 HR02 reservation。

## 66.8 工号并发

已补 sequence/lock。

## 66.9 多部门任务的阻断级别

从 required bool 升级。

## 66.10 Task Dependency

已补 DAG。

## 66.11 Provisioning 外部失败

已补 retry/reconciliation，且不错误回滚真实 HR 事实。

## 66.12 HR04 材料复用

已明确信任策略。

## 66.13 档案到校

已作为高校特色事实模型。

## 66.14 银行/工资

不越界 HR15。

## 66.15 合同

不越界 HR07。

## 66.16 教务身份

集成任务，不写死 HR05。

## 66.17 试用期延长

新增 event，不覆盖日期。

## 66.18 转正失败

不直接删除/禁用员工。

## 66.19 历史迁移

不重复触发副作用。

## 66.20 多学校隐私

Person/Prehire 均 tenant-private。

## 66.21 数据来源冲突

已补 DataConflict。

## 66.22 模板变更污染历史

Case 固定 template version。

## 66.23 Portal 与正式账号混用

已分离。

## 66.24 “100%完成”误导

完成定义与阻断项分离。

---

# 67. AI 施工顺序

AI 收到本总册后先拆任务，不得立即大改。

## HR05-S0 基线复审

逐目录：

```text
onboarding/
recruitment/
employee/
base/
horilla_auth/
horilla_documents/
horilla_audit/
notifications/
```

重点读取：

```text
OnboardingStage
OnboardingTask
CandidateStage
CandidateTask
OnboardingPortal
employee_creation
user_creation
bank detail
candidate stage update
required task gate
dashboard
```

输出：

```text
HR05_GAP_MATRIX.md
LegacyOnboardingMapping.md
RecruitToHireMapping.md
HR05_TASK_TREE.md
HR05_RISK_REGISTER.md
```

S0 不做大改。

## HR05-S1

契约、enum、permissions、公共组件、API envelope。

## HR05-S2

Template/Case/Task/Material/Probation 权威模型和 migrations。

## HR05-S3

HR05-01 待报到人员 + Portal。

## HR05-S4

HR05-02 报到登记 + Activation Gate + HR02/HR03 transaction。

## HR05-S5

HR05-03 入职材料核验。

## HR05-S6

HR05-04 入职协同任务 + Provisioning。

## HR05-S7

HR05-05 试用与转正。

## HR05-S8

Horilla Legacy Projection。

## HR05-S9

Legacy Migration + DUAL_READ_COMPARE。

## HR05-S10

全量安全、并发、性能、E2E、视觉、Accessibility。

## HR05-S11

Authority 切换演练。

## HR05-S12

封板。

只有：

```text
HR05 READY FOR ACCEPTANCE
```

才算完成。

---

# 68. AI 禁止越界

不得：

- 顺手重写 HR02/03/04；
- 把 HR07 合同全部做进 HR05；
- 把 HR15 工资引擎做进 HR05；
- 直接删除 Horilla onboarding；
- Portal 直接 Employee.save；
- 报到即账号全部成功；
- 用 mock SSO 冒充开通；
- 为 CI 绿跳测试；
- 用 CSS 隐藏敏感字段代替后端裁剪；
- 放宽 tenant；
- 同步长任务；
- 绕过 Activation Service 写 HR03；
- 把旧 CandidateStage 当权威历史；
- 自动 fallback legacy。

---

# 69. 最终封板条件

业务：

- 5 个三级模块全闭环；
- HR04 → HR05 → HR03 通；
- HR02 Position commit 正确；
- Portal/报到/激活/协同/转正闭环；
- 放弃/延期/No-show/失败路径真实。

数据：

- template version；
- activation snapshot；
- transition ledger；
- material verification；
- task history；
- probation history；
- Legacy mapping/对账完整。

安全：

- tenant；
- scope；
- portal；
- high-sensitive；
- token；
- access audit；
- file security。

技术：

- DB constraints；
- idempotency；
- transactions；
- outbox；
- retries；
- reconciliation；
- API version；
- migrations；
- rollback。

前端：

- 管理端 + Portal；
- 375/768/1280/1440；
- visual regression；
- accessibility；
- empty/error/blocked/partial。

只有全部通过：

```text
HR05 READY FOR ACCEPTANCE
```

否则：

```text
HR05 NOT READY
blocking:
- ...
```

---

# 70. 最终架构冻结图

```text
HR04
Offer / ProposedHire
        │
        │ HANDOFF
        ▼
┌───────────────────────┐
│ HR05 Onboarding Case  │
└───────────────────────┘
        │
        ├─ HR05-01 Prehire / 待报到
        │
        ├─ HR05-02 Report / 报到
        │          │
        │          ├─ HR02 Position Reservation
        │          │       HELD → COMMITTED
        │          │
        │          └─ HR03 Activation
        │                  Person
        │                  StaffMaster
        │                  Employment
        │                  Assignment
        │
        ├─ HR05-03 Materials
        │
        ├─ HR05-04 Task Orchestration
        │          ├ IAM
        │          ├ Email/OA
        │          ├ Finance
        │          ├ Campus Card
        │          ├ College
        │          └ Academic
        │
        └─ HR05-05 Probation
                   │
                   └→ HR03 / HR07 / HR16 lifecycle event
```

Horilla：

```text
OnboardingStage
OnboardingTask
CandidateStage
CandidateTask
OnboardingPortal
Kanban
Dashboard
        │
        ▼
Legacy Adapter / Projection
        │
        ▼
HR05 Authority
```

最终原则：

> **Horilla Onboarding 是一套很有价值的“阶段 + 任务 + Portal + Kanban”骨架；跃科 HR05 不应推倒它，而应把“合法来源、报到事实、材料证据、正式生效事务、岗位占用、权威人员创建、跨部门 provisioning、试用转正”补成高校生产级事实链，并让 Horilla 原有优秀交互逐步变成新权威模型的工作界面。**

---

# 71. 本轮参考依据

成熟 HCM 方法论重点参考：

- Workday Onboarding Plans：Pre-Hire/New Hire、分阶段任务、Onboarding Planner、安全与业务流程联动；
- SAP SuccessFactors Onboarding：New Hire Data Review、Personal Data Collection、角色化任务、Recruit-to-Hire mapping、preboarding；
- Oracle Journeys：Journey Template、个性化任务、Onboarding Journey。

中国高校实际入职流程重点参考：

- 南开大学新教工信息采集：报到后激活人事系统、统一身份、个人信息完善、人事审核、合同/身份证/学历学位/工作经历/职称等材料；
- 同济大学新进教职工注册报到：招聘账号沿用、入职意愿确认、人事报到与校内业务协同；
- 湖南大学新进教师报到：工号、人事系统补录、学院审核、校园卡；
- 西安工程大学 2026 新进教职工报到：线上注册、合同、现场报到、学历学位、工作经历、无犯罪、报到通知单；
- 山东大学：报到登记、新建教职工编号、人事系统开通；
- 厦门大学：线上报到系统与分步手续。

具体学校政策、材料清单、试用规则、是否阻断入职等不得写死为全国统一规则，应使用 policy/template version 配置。

---

# 72. 编码 AI 首条执行指令

```text
读取《05_HR05_入职管理_施工总册_终极版.md》。

先不要修改业务代码。

完成 HR05-S0：
1. 逐目录审计 Horilla onboarding/recruitment/employee/base/auth/documents/audit/notifications；
2. 重点审查 OnboardingStage、OnboardingTask、CandidateStage、CandidateTask、OnboardingPortal 以及 user_creation/employee_creation/bank-details/token 链；
3. 输出 KEEP / ADAPT / LEGACY_PROJECTION / REWRITE / NEW；
4. 创建 LegacyOnboardingMapping；
5. 创建 RecruitToHireMapping；
6. 对照 HR05 五个三级模块输出 Gap Matrix；
7. 检查 A0、HR02、HR03、HR04 依赖；
8. 输出 S1-S12 文件级任务树；
9. 标记 P0 权限、PII、状态机、事务、岗位容量、账号副作用和并发风险；
10. 不合并 main，不删除 Horilla legacy，不用 mock 冒充业务完成。

S0 通过复审后，再严格按 S1 → S12 施工。
每阶段跑对应测试并报告真实结果。
```

---

**文档状态：V1.0 终极冻结版。**
