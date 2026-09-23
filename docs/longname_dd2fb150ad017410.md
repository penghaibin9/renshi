# 04_HR04_招聘与人才引进_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API（`/api/v1/hr`）、数据库目标（MySQL-only）、事件、权限、Legacy、审计、安全和最终生产 Gate。
> PATCH-04 统一：`Authority Strategy = REWRITE`；`Legacy Technical Reuse = ADAPT`。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR04 招聘与人才引进  
> 三级模块数量：6  
> 总体接管策略：ADAPT  
> 版本：V1.0 终极冻结版  
> 文档性质：HR04 唯一权威施工事实源；可直接整份交给编码 AI 执行“Horilla 招聘基线复审 → Legacy 映射 → 任务拆解 → 高校招聘权威模型 → API → 管理端 → 应聘门户 → 数据迁移/双读对账 → 测试 → 收口”的生产级施工。  
> 适配底座：Horilla HRMS 2.0（当前 `penghaibin9/renshi` 基线）  
> 前置标准：继承《01_HR01_人事工作台_施工总册_终极版》《02_HR02_组织机构与编制岗位_施工总册_终极版》《03_HR03_教职工主档_施工总册_终极版》的 A0 多学校 fail-closed、API 版本化、错误信封、公共 UI、数据新鲜度、Legacy 退出、异步任务、审计、可观测性、Excel、敏感字段和 AI 施工纪律。  
> 重要边界：H0/A0 未封板前，HR04 只能设计/开发，不得标记生产完成；HR02 未提供稳定组织/岗位/岗位额度/预占能力前，不得把 Horilla `JobPosition` 固化为招聘岗位权威外键；HR03 未稳定前，不得把 Candidate 直接转换为新的权威 StaffMaster。  
> 编写日期：2026-08-08  
> 当前策略关键词：**复用 Horilla 招聘交互骨架，重建高校招聘业务真相。**

---

# 0. 结论先行

HR04 不是“招聘职位 + 候选人看板”，也不是把 Horilla Recruitment 改成中文。

HR04 是高校从“为什么要招这个人”到“这个人已经具备进入 HR05 报到入职的合法事实基础”的完整招聘事实链：

```text
年度用人计划
    ↓
招聘批次 / 招聘岗位
    ↓
公告发布
    ↓
候选人报名 / 应聘申请
    ↓
资格审查
    ├─ RETURNED：材料不完整，可补正
    ├─ QUALIFIED：资格通过
    └─ DISQUALIFIED：资格不符，终局或进入复核
    ↓
考试 / 笔试 / 试讲 / 面试 / 技能测试
    ↓
体检 / 考察 / 政审（按学校制度）
    ↓
拟录用
    ↓
公示 / 异议 / 复核
    ↓
Offer / 录用确认
    ↓
HANDOFF_TO_HR05
    ↓
HR05 待报到与入职
```

HR04 必须同时回答六个根本问题：

1. **学校为什么要招、招多少、占什么编制/岗位额度？** —— HR04-01 年度用人计划；
2. **这一批真正公开招聘什么岗位、资格条件是什么、公告版本是什么？** —— HR04-02 招聘项目与岗位；
3. **这个自然人是谁，他投了哪个岗位、提交了哪些材料、经历过哪些招聘？** —— HR04-03 人才库与应聘者；
4. **他是否满足当时冻结的岗位资格条件，补材料和“不合格”是否严格区分？** —— HR04-04 资格审查；
5. **考试、试讲、面试、技能测试、体检与考察是否公平、可追溯、可复核？** —— HR04-05 考试面试与考察；
6. **拟录用、公示、异议、Offer 和进入 HR05 是否形成闭环且不会超招？** —— HR04-06 录用与人才引进。

HR04 的顶级实现必须贯彻五条原则：

> **候选人 ≠ 应聘申请；招聘岗位 ≠ HR02 岗位目录；流程阶段 ≠ 权威状态；资格自动预检 ≠ 自动最终淘汰；“已录用” ≠ “已成为教职工”。**

因此禁止以下低质量实现：

- 直接把 Horilla `Candidate` 当“自然人 + 所有应聘记录”的唯一真相；
- 直接把 Horilla `Stage.stage_type` 当高校招聘权威状态机；
- 把 RETURNED、REJECTED、DISQUALIFIED、WITHDRAWN 全塞进 cancelled；
- 资格条件发布后直接改字段，导致旧申请按新条件重新解释；
- 招聘公告内容修改后不保留公告版本；
- 一个候选人投多个岗位就复制多份“人才”；
- 用 email 作为候选自然人唯一身份；
- 资格审查只做一个“通过/不通过”按钮；
- 系统自动规则不满足就直接淘汰，且不给人工复核；
- 把年龄、性别等不必要条件做成默认筛选项；
- 专家评分可以在结果锁定后直接改；
- 专家能看到与评审无关的身份证、电话、家庭住址等敏感信息；
- 专家和候选人存在利益关系仍可打分；
- 同一个 Position 最后一个空岗被两个招聘项目同时使用；
- “招聘 vacancy=1”只在 UI 上检查，不做数据库事务约束；
- 拟录用后立即创建 HR03 StaffMaster；
- 公示期间已进入正式入职；
- 公示异议直接覆盖原结果，没有异议案件；
- Offer 接受和 HR05 handoff 没有幂等；
- 公告、资格条件、评分方案、专家分组没有版本；
- 大批量候选人 Excel 导入同步逐行 save；
- 公开报名附件长期暴露 `/media/...` 裸 URL；
- 候选人页面泄漏其他候选人的存在、分数或排序；
- 将 AI 简历筛选结果作为不可解释的最终资格否决；
- 通过移动卡片到另一个 Stage 就直接改正式业务状态；
- LinkedIn 等外部渠道成为核心依赖；
- 页面“很漂亮”但无法回答“此人为什么通过/为什么不通过”。

---

# 1. 施工前提与依赖

## 1.1 H0/A0 硬门

HR04 处理外部候选人 PII、招聘材料和公平性事实，A0 至少必须达到：

- tenant / 学校由可信上下文解析；
- 无 tenant context fail-closed；
- 所有内部管理员 API 先 tenant、再 data scope、再 permission；
- 公开报名入口必须由招聘批次/岗位的公开 token 或 public slug 解析学校，不允许客户端随意传 `tenant_id`；
- public endpoint 不得通过枚举 ID 访问其他学校招聘；
- 上传材料按 tenant + recruitment + candidate 隔离；
- 后台任务显式 tenant；
- 外部候选人数据严禁进入平台跨校共享池；
- 平台运维默认不可查看候选人 PII；
- break-glass 访问必须有 reason、审批/授权和审计；
- 日志不得输出身份证、完整手机号、简历正文等敏感内容；
- rate limit、验证码/反自动化、恶意附件防护必须具备；
- public portal 与员工/HR 管理账号体系隔离。

## 1.2 HR02 依赖硬门

招聘岗位不能再直接以 Horilla `JobPosition` 作为长期权威。

HR02 至少必须提供：

```text
HrOrganization
HrPostCatalog
HrPosition / HrPositionPool
HrStaffingPlan
HrPositionReservation
```

HR04 需要调用：

- 查询可招聘组织；
- 查询岗位目录；
- 查询实际可用岗位额度；
- 预占 Position/Pool；
- 释放预占；
- 在拟录用/HR05 接管时延长或提交预占；
- 检查组织/岗位在招聘期间是否关闭或发生重大变更。

关键规则：

> **招聘需求是“对岗位额度的业务占用请求”，不能只是 Recruitment.vacancy 一个整数。**

## 1.3 HR03 边界

HR04 的 Candidate 不是 HR03 的 Person。

HR04 可以为了候选人去重建立 `HrRecruitmentCandidate`，但其语义是：

> “某学校招聘域中的候选自然人身份”。

只有在 HR04 最终录用、HR05 正式报到并满足入职确认条件后，HR05 才调用 HR03：

```text
match_or_create HrPerson
→ create/activate HrStaffMaster
→ create EmploymentRelationship
→ create Assignment
```

禁止：

```text
HR04 Hired
→ 直接 Employee.save()
→ 自动创建账号
```

## 1.4 HR05 边界

HR04 负责到：

```text
录用结论有效
+ 公示/异议闭环
+ Offer 状态明确
+ 录用材料包冻结
+ 招聘来源、岗位、计划和资格事实完整
```

HR05 从：

```text
待报到
→ 自助采集入职资料
→ 核验
→ 工号/账号
→ 合同
→ 部门/岗位 assignment
→ 入职协同任务
```

开始。

`HANDOFF_TO_HR05` 必须是显式、幂等、可审计的领域动作。

## 1.5 HR01 / HR18 依赖

HR04 为 HR01 提供：

- 当前招聘项目；
- 招聘岗位数；
- 报名人数；
- 待资格审核；
- 待面试/试讲；
- 拟录用/待公示；
- 招聘超期风险。

HR04 为 HR18 提供：

- 招聘计划完成率；
- 报名→资格通过→面试→录用漏斗；
- 岗位招聘周期；
- 到岗率；
- 招聘来源；
- 学院/岗位招聘结构；
- 不合格原因统计；
- 公示异议统计。

统计必须使用规范业务事件，不从 UI Stage 名称反推。

---

# 2. 三家成熟 HCM 对标：共同精华

> 本节只吸收成熟 HCM 的产品方法论，不复制厂商 UI、代码或私有实现。Workday Recruiting、SAP SuccessFactors Recruiting、Oracle Recruiting Cloud 的共同价值不在“都有候选人列表”，而在于招聘需求、候选人体验、可配置流程、权限、数据分析和与 Core HR 的闭环。

## 2.1 Workday Recruiting：招聘与组织/岗位事实同源

应吸收：

- 招聘需求与组织、岗位、headcount/position 管理强关联；
- recruiter、hiring manager、interviewer 看到不同职责视图；
- 候选人状态和下一行动处于同一工作流；
- 候选人体验与内部招聘处理形成同一事实链；
- 招聘分析可直接钻取到待处理对象；
- 招聘完成后自然衔接 onboarding / worker 创建，而不是人工重复录入。

转化为跃科：

```text
HR02 Position/Pool
    ↓ reservation
HR04 RecruitmentPosition
    ↓
Application
    ↓
Selection
    ↓
ProposedHire
    ↓
HR05
```

## 2.2 SAP SuccessFactors Recruiting：Requisition + Candidate + Application

最值得吸收的是对象分层：

- Job Requisition 是招聘需求/职位；
- Candidate 是候选自然人；
- Job Application 是候选人对某岗位的某次申请；
- 可配置招聘状态；
- 候选门户和 recruiter 工作台分离；
- 招聘模板/字段/权限可按场景配置；
- applicant/candidate 数据需要 retention 与 consent 管理；
- 状态和动作按权限/角色裁剪。

转化为跃科：

> **Horilla Candidate 当前“一条记录绑一个 Recruitment”的设计必须被 Application 层解耦。**

## 2.3 Oracle Recruiting Cloud：统一候选体验 + 招聘流程 + Offer/Onboarding 衔接

应吸收：

- 招聘岗位、候选人、申请、面试、Offer 明确分层；
- candidate-facing portal 与内部 recruiter experience 协同；
- 筛选、评估、面试和 offer 是不同阶段对象；
- 支持模板化招聘流程；
- 录用结果与 Core HR / onboarding 衔接；
- 报表和安全沿用统一 HCM 基础能力。

## 2.4 三家共同精华冻结

HR04 必须吸收：

1. **岗位需求先于候选人**；
2. **Candidate 与 Application 分离**；
3. **流程可配置，但权威状态不可随意配置**；
4. **候选人自助门户与 HR 后台职责分离**；
5. **招聘状态必须可以解释“现在为什么在这里”**；
6. **每一步都有 owner / due date / next action**；
7. **招聘完成不是 Core HR 自动生效，而是合法 handoff**；
8. **Recruiter / 学院 / 专家权限不同**；
9. **高敏信息最小化暴露**；
10. **数据分析与具体业务对象可钻取**。

---

# 3. 中国高校招聘与人才引进业务校正

普通企业招聘不能直接覆盖高校。

高校招聘常见事实链包括：

```text
学院用人需求
→ 学校年度用人计划
→ 编制/岗位审核
→ 招聘公告
→ 报名
→ 资格审查
→ 笔试/专业测试/试讲/面试/技能测试
→ 体检
→ 考察
→ 拟聘
→ 公示
→ 审批/备案
→ 报到
```

不同学校、岗位类别可以不同，所以系统必须是：

```text
Canonical State Machine
+
Recruitment Workflow Template
+
Position-specific Selection Scheme
```

而不是写死“一定三轮面试”。

## 3.1 高校岗位类型差异

至少要支持：

- 专任教师；
- 实验/实训教师；
- 辅导员；
- 行政管理；
- 其他专业技术；
- 高层次人才；
- 博士/博士后专项；
- 技能大师/产业导师；
- 编外/合同制；
- 外聘（HR08 主域，HR04 可作为来源）。

不同岗位允许不同选拔组件：

```text
DOCUMENT_REVIEW
WRITTEN_EXAM
TEACHING_DEMO
PROFESSIONAL_TEST
SKILL_TEST
INTERVIEW
PSYCHOLOGICAL_TEST（若合法且必要）
MEDICAL_CHECK
BACKGROUND_CHECK
```

## 3.2 RETURNED 必须独立

高校资格审查最常见的低质量系统问题：

> “材料不全”直接等于“不合格”。

必须严格区分：

```text
RETURNED
= 材料缺失/格式问题/可补正
= 可重新提交

DISQUALIFIED
= 明确不满足冻结条件
= 终局或进入复核/申诉

WITHDRAWN
= 候选人主动撤回
```

## 3.3 资格规则只能“辅助预检”

规则引擎可以检查：

- 学历层次；
- 学位；
- 专业；
- 年龄区间（仅在合法公告明确要求时）；
- 职称；
- 工作年限；
- 教师资格；
- 职业资格；
- 其他公告结构化条件。

但系统不得默认自动作出最终“不合格”结论。

规则输出：

```text
PASS
FAIL
NEEDS_MANUAL_REVIEW
DATA_MISSING
```

最终资格结论必须记录人工审核人和依据。

## 3.4 招聘条件必须冻结版本

招聘岗位发布后：

```text
QualificationRuleSet v3
SelectionScheme v2
Announcement v5
```

必须与 Application 绑定。

如果学校修改公告：

- 创建 amendment；
- 记录生效时间；
- 记录修改原因；
- 决定是否影响已提交申请；
- 必要时通知受影响候选人；
- 禁止静默覆盖旧条件。

## 3.5 专家评审必须支持回避

至少支持：

- 本人声明利益冲突；
- 管理员预设回避；
- 同单位/师生/亲属等学校配置规则；
- 冲突后不可访问候选评分页；
- 专家只能看 assigned candidates；
- 可配置盲评字段；
- 评分提交后锁定；
- 解锁必须特权 + reason + audit。

---

# 4. Horilla 2.0 招聘现状审计与 ADAPT 判定

## 4.1 值得高价值复用的能力

当前 Horilla Recruitment 已有：

- `Recruitment`；
- 单岗位/多岗位 event-based recruitment；
- vacancy；
- recruitment managers；
- survey templates；
- publish/close；
- start/end date；
- skill；
- `Stage` 自定义阶段和 sequence；
- Pipeline；
- `Candidate`；
- Candidate stage drag/drop；
- candidate history；
- rating；
- interview schedule；
- notes/files；
- mail；
- rejected candidate / reject reason；
- recruitment survey；
- candidate document request；
- public application form；
- candidate export；
- onboarding start / converted employee；
- dashboard / vacancy / hiring pipeline；
- company-scoped manager。

这些是 HR04 选择 **ADAPT 而不是 REWRITE** 的主要原因。

## 4.2 Horilla Recruitment 不足

`Recruitment` 当前主要是：

```text
title
description
is_event_based
closed
is_published
open_positions(JobPosition)
vacancy
recruitment_managers
survey_templates
company
start_date/end_date
skills
linkedin
```

缺少：

- 年度用人计划；
- 计划审批；
- HR02 编制/Position reservation；
- 招聘项目与岗位分层；
- 招聘公告版本；
- 岗位资格条件版本；
- 招聘来源/政策依据；
- 岗位选择方案；
- 公示；
- 体检/考察正式事实；
- Offer 与拟录用分层；
- 录用审批；
- 备案/批复；
- 计划额度消耗。

结论：

```text
Recruitment Model      ADAPT → Legacy Campaign Projection
Recruitment Pipeline   KEEP/ADAPT 交互层
New HR04 authority     NEW
```

## 4.3 Horilla Stage 最大风险

当前 Stage type 只有：

```text
initial
applied
test
interview
cancelled
hired
```

高校至少需要：

```text
DRAFT
SUBMITTED
UNDER_REVIEW
RETURNED
QUALIFIED
DISQUALIFIED
ASSESSMENT_PENDING
ASSESSING
ASSESSMENT_PASSED
ASSESSMENT_FAILED
MEDICAL_PENDING
BACKGROUND_PENDING
PROPOSED_HIRE
PUBLIC_NOTICE
OFFERED
OFFER_ACCEPTED
OFFER_DECLINED
HANDOFF_TO_HR05
WITHDRAWN
CANCELLED
```

不能靠用户自由改 Stage 名称解决。

最终必须分层：

```text
CanonicalStatus
= 系统权威业务状态

WorkflowStage
= 学校招聘流程的展示阶段/工作队列

Horilla Stage
= 兼容 Projection / Pipeline UI
```

## 4.4 Horilla Candidate 最大风险

当前 `Candidate` 同时绑定：

```text
recruitment_id
job_position_id
stage_id
email
resume
...
```

这意味着：

> Candidate 实际更接近“某次申请”，而不是“人才/自然人”。

必须拆：

```text
HrRecruitmentCandidate
  └─ HrJobApplication[]
```

一个候选人：

```text
张三
├─ 2026 专任教师-软件工程 Application A
├─ 2026 实验教师 Application B
└─ 2027 人工智能教师 Application C
```

人才库只保留一份招聘域候选身份，不复制 3 个人。

## 4.5 RejectedCandidate 接管

可复用：

- reject reason catalog；
- reject notes；
- history。

必须重构：

- 不再把所有终止状态都叫 rejected；
- reason 与 `decision_type` 绑定；
- RETURNED 使用 correction/material request，不进入 reject；
- DISQUALIFIED 记录不符合哪条冻结规则；
- WITHDRAWN 由候选人动作产生；
- FAILED_ASSESSMENT 与资格不合格分开。

## 4.6 Survey 接管

Horilla survey 支持：

- yes/no；
- choices；
- multiple；
- text；
- number；
- percentage；
- date；
- textarea；
- file；
- rating。

值得 KEEP/ADAPT。

但正式岗位资格条件不能完全依赖 survey 自由题。

分工：

```text
QualificationRuleSet
= 正式结构化资格条件

ApplicationFormSchema
= 报名采集字段

Survey
= 补充问题/招聘问卷
```

## 4.7 Interview 接管

Horilla 已有 InterviewSchedule、interview managers、candidate interview view。

继续复用：

- 排期；
- interviewer assignment；
- 通知；
- 面试列表/详情交互。

必须新增：

- selection component；
- room/online mode；
- conflict checking；
- expert recusal；
- score sheet；
- weighted scoring；
- attendance；
- no-show；
- score lock；
- abnormal score；
- review/reopen audit。

## 4.8 CandidateDocument 接管

继续 ADAPT 文件上传与格式/大小校验。

新增：

- material type；
- required/conditional；
- version；
- SHA-256；
- verification status；
- reviewer；
- linked qualification rule；
- sensitive level；
- retention；
- secure preview/download ticket；
- malware scan status；
- replacement history。

## 4.9 LinkedIn

`LinkedInAccount` 不属于高校招聘核心闭环。

V1：

```text
LinkedIn publishing = OPTIONAL / DISABLED BY DEFAULT
```

不得阻塞高校招聘主链路。

---

# 5. HR04 信息架构冻结

```text
HR04 招聘与人才引进
├─ HR04-01 年度用人计划
├─ HR04-02 招聘项目与岗位
├─ HR04-03 人才库与应聘者
├─ HR04-04 资格审查
├─ HR04-05 考试面试与考察
└─ HR04-06 录用与人才引进
```

六个三级模块冻结，不再增加同层级菜单。

## 5.1 默认入口

HR04 默认进入：

**HR04 招聘控制台 / HR04-02 招聘项目与岗位**

顶部提供：

- 当前招聘项目；
- 待资格审核；
- 本周考试面试；
- 待公示；
- 待 Offer；
- 超期风险。

但不新建 HR04-00 菜单，作为 HR04-02 的控制台首屏。

## 5.2 六模块职责不重复

- HR04-01 管“为什么招、允许招多少”；
- HR04-02 管“这一批怎么招、公开招什么”；
- HR04-03 管“谁来应聘、投了什么”；
- HR04-04 管“是否符合资格”；
- HR04-05 管“选拔成绩与考察事实”；
- HR04-06 管“最终录用结论与 HR05 handoff”。

---

# 6. 角色与数据范围

## 6.1 角色

### HR_RECRUITMENT_ADMIN

全校招聘管理员：

- 管招聘计划/项目；
- 配岗位；
- 管资格审核；
- 管专家/考试；
- 管拟录用/公示；
- 导出全校招聘数据。

### HR_RECRUITMENT_DIRECTOR

- 审批高风险动作；
- 批准计划/发布/结果；
- 处理重大异议和解锁评分。

### COLLEGE_RECRUITER

- 仅本学院 scope；
- 发起用人需求；
- 参与资格初审；
- 安排学院级试讲/面试；
- 不得看到其他学院申请。

### HIRING_MANAGER

- 仅授权岗位；
- 查看必要候选信息；
- 参与面试；
- 不看高敏 PII。

### QUALIFICATION_REVIEWER

- 仅分配岗位/申请；
- 查看资格条件和必要材料；
- 不能查看不相关敏感信息；
- 可 RETURN / QUALIFY / DISQUALIFY（按权限）。

### EXPERT_EVALUATOR

- 仅 assigned sessions/candidates；
- 盲评时隐藏姓名/联系方式等；
- 提交评分后锁定。

### PUBLIC_NOTICE_ADMIN

- 管公示；
- 不等于招聘全权限。

### AUDITOR

- 查过程、访问、变更和评分解锁；
- 不天然拥有全部 PII 明文。

### CANDIDATE

- 仅本人；
- 报名；
- 补材料；
- 查看本人状态/通知；
- 撤回申请；
- 接受/拒绝 Offer。

## 6.2 Data Scope

```text
SCHOOL
COLLEGE
ORGANIZATION
RECRUITMENT_CAMPAIGN
RECRUITMENT_POSITION
ASSIGNED_APPLICATION_SET
SELF
```

## 6.3 权限示例

```text
hr04.plan.view
hr04.plan.create
hr04.plan.approve

hr04.campaign.view
hr04.campaign.manage
hr04.campaign.publish

hr04.application.view
hr04.application.sensitive_view
hr04.application.export

hr04.qualification.review
hr04.qualification.finalize

hr04.assessment.manage
hr04.assessment.score
hr04.assessment.unlock_score

hr04.proposed_hire.manage
hr04.public_notice.publish
hr04.offer.manage
hr04.handoff_hr05
```

---

# 7. 权威领域模型总览

```text
HrHiringPlanCycle
  └─ HrHiringPlanRequest
       └─ HrHiringPlanLine
            └─ HrPositionReservation

HrRecruitmentCampaign
  ├─ HrRecruitmentPosition
  │    ├─ HrRecruitmentAnnouncementVersion
  │    ├─ HrQualificationRuleSetVersion
  │    └─ HrSelectionSchemeVersion
  │
  └─ HrRecruitmentCandidate
       └─ HrJobApplication
            ├─ HrApplicationMaterial[]
            ├─ HrQualificationReview[]
            ├─ HrApplicationTransition[]
            ├─ HrAssessmentParticipant[]
            ├─ HrMedicalCheck
            ├─ HrBackgroundCheck
            ├─ HrProposedHire
            ├─ HrPublicNoticeCase
            └─ HrRecruitmentOffer
```

---

# 8. HR04-01 年度用人计划施工卡

## 8.1 业务目标

让学校真正回答：

- 哪个学院想招人？
- 为什么招？
- 招什么岗位？
- 属于新增、补充、替补还是人才引进？
- HR02 有无编制/岗位额度？
- 学校最终批准多少？
- 后续招聘是否超出批准计划？

## 8.2 页面

路由：

```text
/hr/recruitment/plans
/hr/recruitment/plans/:id
/hr/recruitment/plans/:id/requests/:requestId
```

### 列表页

```text
┌────────────────────────────────────────────────────────────┐
│ 年度用人计划  2027年度                [新建计划周期] [导出] │
│ 当前学校：XX职业技术学院   口径：已批准计划                 │
├────────────────────────────────────────────────────────────┤
│ 申请 86 │ 批准 52 │ 已启动招聘 31 │ 已录用 18 │ 剩余额度 34 │
├────────────────────────────────────────────────────────────┤
│ [全部][待学院提交][待人事审核][待学校审批][已批准][已关闭]  │
├────────────────────────────────────────────────────────────┤
│ 学院 | 申请人数 | 批准人数 | 招聘中 | 已录用 | 剩余 | 状态  │
└────────────────────────────────────────────────────────────┘
```

### 需求详情

三栏：

1. **需求事实**
   - 组织；
   - 岗位目录；
   - 需求人数；
   - 人员类别；
   - 原因；
   - 计划到岗日期。

2. **HR02 资源校验**
   - 编制核定；
   - 当前占用；
   - 空岗；
   - 已被其他流程预占；
   - 本申请可申请额度。

3. **审批时间线**
   - 学院；
   - 人事；
   - 校级；
   - 退回原因。

## 8.3 模型

```text
HrHiringPlanCycle
- id UUID
- tenant_id
- year
- title
- start_date
- end_date
- status
- version
- created_by
- created_at

HrHiringPlanRequest
- id
- tenant_id
- cycle_id
- organization_id
- requested_by
- status
- total_requested
- total_approved
- submitted_at
- approved_at
- version

HrHiringPlanLine
- id
- tenant_id
- request_id
- post_catalog_id
- position_id nullable
- position_pool_id nullable
- need_type            NEW / REPLACEMENT / TALENT / TEMPORARY
- requested_headcount
- approved_headcount
- requested_fte
- approved_fte
- target_onboard_date
- reason
- qualification_summary
- status
- version
```

## 8.4 状态

```text
DRAFT
→ SUBMITTED
→ UNDER_HR_REVIEW
→ RETURNED
→ RESUBMITTED
→ UNDER_SCHOOL_APPROVAL
→ APPROVED
→ PARTIALLY_APPROVED
→ REJECTED
→ CLOSED
```

RETURNED ≠ REJECTED。

## 8.5 API

```http
GET    /api/hr/v1/recruitment/plans
POST   /api/hr/v1/recruitment/plans
GET    /api/hr/v1/recruitment/plans/{id}
POST   /api/hr/v1/recruitment/plans/{id}/submit
POST   /api/hr/v1/recruitment/plans/{id}/approve

POST   /api/hr/v1/recruitment/plan-requests
PATCH  /api/hr/v1/recruitment/plan-requests/{id}
POST   /api/hr/v1/recruitment/plan-requests/{id}/submit
POST   /api/hr/v1/recruitment/plan-requests/{id}/return
POST   /api/hr/v1/recruitment/plan-requests/{id}/approve
```

所有响应根：

```json
{
  "apiVersion": "v1",
  "schemaVersion": "hr04.1",
  "requestId": "...",
  "data": {}
}
```

V1 additive-only。

## 8.6 并发

批准时必须重新查询 HR02 可用额度。

禁止：

```text
页面打开时显示还有2个
→ 30分钟后仍直接approve 2个
```

必须事务重检。

---

# 9. HR04-02 招聘项目与岗位施工卡

## 9.1 目标

把年度批准计划变成可执行、可公开、可追溯招聘批次。

## 9.2 页面

```text
/hr/recruitment/campaigns
/hr/recruitment/campaigns/:id
/hr/recruitment/campaigns/:id/positions/:positionId
/hr/recruitment/campaigns/:id/publish
```

### 招聘控制台

顶部 5 KPI：

- 进行中项目；
- 开放岗位；
- 待资格审核；
- 本周选拔；
- 待拟录用。

下面：

```text
招聘漏斗
招聘项目卡
超期岗位
近期截止
```

### 招聘项目详情

Tabs：

```text
概览
招聘岗位
流程配置
公告版本
申请统计
考试面试
录用结果
通知
审计
```

### 招聘岗位详情

首屏必须显示：

```text
软件工程专任教师
计划：2人
HR02岗位额度：2
已预占：2
报名：86
资格通过：32
当前阶段：面试
公告截止：2026-09-30
```

## 9.3 模型

```text
HrRecruitmentCampaign
- id
- tenant_id
- code
- title
- campaign_type
- plan_cycle_id
- status
- public_slug
- application_open_at
- application_close_at
- timezone
- manager_ids
- version

HrRecruitmentPosition
- id
- tenant_id
- campaign_id
- hiring_plan_line_id
- organization_id
- post_catalog_id
- position_id nullable
- position_pool_id nullable
- planned_headcount
- reserved_headcount
- min_hires
- max_hires
- status
- qualification_rule_version_id
- selection_scheme_version_id
- version

HrRecruitmentAnnouncementVersion
- id
- tenant_id
- campaign_id
- version_no
- content
- attachment_ids
- effective_at
- published_at
- change_reason
- supersedes_id
- immutable_after_publish
```

## 9.4 Campaign 状态

```text
DRAFT
→ UNDER_APPROVAL
→ APPROVED
→ PUBLISHED
→ OPEN
→ CLOSED
→ RESULT_PROCESSING
→ COMPLETED
→ ARCHIVED
```

## 9.5 Position 状态

```text
DRAFT
→ READY
→ OPEN
→ CLOSED
→ SELECTION
→ PROPOSED_HIRE
→ FILLED
→ PARTIALLY_FILLED
→ CANCELLED
```

## 9.6 HR02 Reservation

招聘岗位 READY/OPEN 前：

```text
reserve(position/pool, headcount, recruitment_position_id)
```

reservation：

```text
HELD
COMMITTED
RELEASED
EXPIRED
```

招聘取消/关闭未录用额度必须 release。

## 9.7 Horilla 兼容

```text
HrRecruitmentCampaign
      ↓ projection
Horilla Recruitment

HrRecruitmentPosition
      ↓
Recruitment.open_positions / job_position
```

Horilla `vacancy` 只作为兼容展示值，不再是额度权威。

---

# 10. HR04-03 人才库与应聘者施工卡

## 10.1 目标

建立：

```text
候选自然人
≠
某岗位某次申请
```

## 10.2 管理端页面

```text
/hr/recruitment/candidates
/hr/recruitment/candidates/:candidateId
/hr/recruitment/applications/:applicationId
```

### 人才库

列：

- 姓名；
- 当前/最近应聘岗位；
- 学历；
- 专业；
- 职称；
- 来源；
- 最近申请时间；
- 人才标签；
- 当前状态；
- 历史申请数。

搜索：

- 姓名；
- 候选编号；
- 招聘项目；
- 学院；
- 岗位；
- 学历；
- 专业；
- 状态。

敏感搜索：

身份证 exact-search 单独受控接口，不进入普通模糊搜索。

### 候选人详情

顶部：

```text
候选编号
姓名
当前联系方式（按权限遮罩）
人才标签
历史申请 3
```

Tabs：

```text
基本资料
教育经历
工作经历
资格证书
应聘记录
材料
沟通记录
访问/变更审计
```

### Application 详情

```text
左：岗位/公告/资格版本
中：申请资料、材料、流程时间线
右：当前状态、下一动作、负责人、截止时间
```

## 10.3 Candidate 模型

```text
HrRecruitmentCandidate
- id UUID
- tenant_id
- candidate_uid immutable
- legal_name
- preferred_name nullable
- primary_email
- primary_mobile
- national_id_cipher nullable
- national_id_hash nullable
- consent_version
- consent_at
- retention_until
- source
- status ACTIVE / ANONYMIZED / BLOCKED
- created_at
```

身份证：

- 加密存储；
- hash 做 tenant-scoped exact match；
- 禁止明文日志；
- 不跨租户 dedupe。

## 10.4 Application

```text
HrJobApplication
- id
- tenant_id
- candidate_id
- recruitment_position_id
- application_no
- submitted_at
- canonical_status
- workflow_stage_id
- current_owner_id
- due_at
- source_channel
- qualification_rule_version_id
- selection_scheme_version_id
- announcement_version_id
- withdrawn_at
- final_decision_at
- version
```

唯一约束按学校规则：

```text
tenant + candidate + recruitment_position + active_application
```

是否允许同批多个岗位由 campaign policy 配置。

## 10.5 Public Portal

```text
/recruit/:tenantSlug/:campaignSlug
/recruit/:tenantSlug/:campaignSlug/positions/:positionSlug
/recruit/apply/:applicationToken
/recruit/my-applications
```

原则：

- Mobile-first；
- 不使用管理员端导航；
- 草稿自动保存；
- 材料上传进度；
- 提交前检查；
- 明确隐私用途；
- 候选人只能看到本人；
- public candidate account 与员工账号隔离。

## 10.6 Candidate 数据生命周期

配置：

```text
retention_policy
consent_version
legal_hold
anonymization policy
```

禁止“招聘没录用就永远保存所有身份证/简历”。

---

# 11. HR04-04 资格审查施工卡

## 11.1 页面是本模块核心卖相页之一

路由：

```text
/hr/recruitment/qualification
/hr/recruitment/qualification/:positionId
/hr/recruitment/applications/:id/qualification
```

### 审核工作台布局

```text
┌─────────────────────────────────────────────────────────────┐
│ 软件工程专任教师 · 资格审查    86份  待审18 退回7 不合格9   │
├───────────────┬───────────────────────────┬─────────────────┤
│ 候选人队列     │ 条件核验矩阵               │ 材料与决策       │
│               │                           │                 │
│ 张三 待审核    │ ✓ 博士                    │ 学历材料 ✓       │
│ 李四 缺材料    │ ✓ 计算机相关专业           │ 学位材料 ✓       │
│ 王五 待复核    │ ? 3年行业经历             │ 企业经历 !       │
│               │ ✓ 年龄条件                 │                 │
│               │                           │ [退回补充]       │
│               │ 系统预检：NEEDS_REVIEW     │ [资格通过]       │
│               │                           │ [不合格]         │
└───────────────┴───────────────────────────┴─────────────────┘
```

顶级 UI 要求：

- 左右切人不丢审核草稿；
- 条件逐条可展开证据；
- 自动预检与人工判断视觉区分；
- FAIL 不默认红色“大叉直接淘汰”，先显示“需人工确认”；
- 操作前必须填写 reason/依据；
- RETURNED 明确列缺失项和补交截止；
- 下一人快捷键；
- 批量审核只允许低风险一致结论，DISQUALIFIED 默认逐件确认。

## 11.2 Rule 模型

```text
HrQualificationRuleSetVersion
- id
- tenant_id
- recruitment_position_id
- version_no
- status DRAFT / LOCKED / ACTIVE / SUPERSEDED
- published_at
- created_by

HrQualificationRule
- id
- rule_set_version_id
- rule_code
- label
- rule_type
- operator
- expected_value_json
- severity HARD / SOFT / INFO
- evidence_requirement
- sequence
```

## 11.3 Review

```text
HrQualificationReview
- id
- tenant_id
- application_id
- rule_id nullable
- system_result
- reviewer_result
- reviewer_id
- evidence_refs
- note
- reviewed_at

HrQualificationDecision
- id
- application_id
- decision
- reason_code
- reason_text
- decided_by
- decided_at
- rule_set_version_id
- version
```

## 11.4 状态机

```text
SUBMITTED
→ UNDER_REVIEW
→ RETURNED
→ RESUBMITTED
→ UNDER_REVIEW
→ QUALIFIED

UNDER_REVIEW
→ DISQUALIFIED
```

不允许：

```text
RETURNED → HIRED
DISQUALIFIED → INTERVIEW
```

除非先通过正式 `REOPEN / REVIEW_OVERRIDDEN` 特权流程。

## 11.5 自动预检

输出：

```text
PASS
FAIL
DATA_MISSING
NEEDS_MANUAL_REVIEW
NOT_APPLICABLE
```

系统只能建议，不得直接最终不合格。

## 11.6 批量操作

允许：

- 批量分配审核人；
- 批量请求同类补件；
- 批量通过“所有 HARD 条件系统可验证 + 无异常”的申请（学校配置）；
- 不合格默认禁止无确认批量执行。

---

# 12. HR04-05 考试面试与考察施工卡

## 12.1 目标

把 Horilla 面试排期升级为完整高校 Selection Engine。

## 12.2 Selection Scheme

```text
HrSelectionSchemeVersion
- id
- tenant_id
- recruitment_position_id
- version_no
- total_score
- passing_rule
- tie_break_rule_json
- locked_at

HrSelectionComponent
- id
- scheme_version_id
- type
- name
- weight
- max_score
- pass_score nullable
- sequence
- is_elimination
```

示例：

```text
资格审查      门槛
笔试          30%
试讲          30%
面试          40%
```

辅导员岗位可能：

```text
笔试 50%
面试 50%
```

高层次人才可：

```text
材料评议
学术评价
综合面谈
```

## 12.3 Assessment Event

```text
HrAssessmentEvent
- id
- tenant_id
- component_id
- title
- date
- start_time
- end_time
- mode ONSITE / ONLINE
- location
- capacity
- status
- version

HrEvaluatorAssignment
- id
- event_id
- evaluator_staff_id
- role
- conflict_status
- recusal_reason
- blind_mode
```

## 12.4 评分

```text
HrScoreSheetTemplate
HrScoreCriterion

HrCandidateScoreSheet
- application_id
- event_id
- evaluator_id
- status DRAFT / SUBMITTED / LOCKED / VOID
- submitted_at
- locked_at
- version

HrCandidateScore
- sheet_id
- criterion_id
- score
- comment
```

总分必须服务端计算。

禁止前端提交 final_total。

## 12.5 专家页面

这是第二个核心“卖相页面”。

```text
顶部：项目 / 岗位 / 当前场次 / 时间
左：候选编号列表
中：候选必要材料 / 代表成果
右：评分表
底：保存草稿 / 提交
```

盲评：

- 显示 Candidate No；
- 隐藏手机号/email/身份证；
- 可配置隐藏姓名、毕业院校等字段；
- 服务端裁剪，不是 CSS 隐藏。

## 12.6 利益冲突

```text
CLEAR
DECLARED
DETECTED
RECUSED
OVERRIDDEN
```

OVERRIDDEN 必须：

- 特权；
- reason；
- approving user；
- audit。

## 12.7 分数锁定

评分提交：

```text
DRAFT → SUBMITTED → LOCKED
```

解锁：

```text
LOCKED
→ REOPEN_REQUESTED
→ REOPEN_APPROVED
→ DRAFT
```

必须保留旧版本。

## 12.8 体检与考察

```text
HrMedicalCheck
- application_id
- status
- scheduled_at
- result FIT / UNFIT / RECHECK / PENDING
- sensitive_material_id
- verified_by

HrBackgroundCheck
- application_id
- status
- result
- summary
- sensitive_material_id
- verified_by
```

医疗信息：

- HIGH_SENSITIVE；
- 招聘普通管理员默认只看结论，不看详细医疗材料。

## 12.9 排期冲突

检查：

- 同一专家时间冲突；
- 同一候选人多场冲突；
- 场地冲突；
- 容量；
- 线上会议冲突；
- 时区。

---

# 13. HR04-06 录用与人才引进施工卡

## 13.1 目标

正式解决：

```text
选拔结果
→ 拟录用
→ 审批
→ 公示
→ 异议
→ Offer
→ HR05
```

而不是“Candidate.hired=True”。

## 13.2 拟录用工作台

```text
/hr/recruitment/proposed-hires
/hr/recruitment/proposed-hires/:id
```

列表：

- 候选人；
- 招聘岗位；
- 综合成绩；
- 排名；
- 岗位额度；
- 资格；
- 体检；
- 考察；
- 公示；
- Offer；
- HR05 状态。

## 13.3 Proposed Hire

```text
HrProposedHire
- id
- tenant_id
- application_id
- recruitment_position_id
- rank
- final_score
- reservation_id
- decision
- decision_reason
- approval_status
- approved_at
- version
```

创建时必须锁定并验证：

- Application 当前合法；
- 资格 QUALIFIED；
- 必要 Selection 完成；
- 必要体检/考察符合；
- HR02 reservation 有效；
- 录用人数不超过上限。

## 13.4 公示

```text
HrPublicNotice
- id
- tenant_id
- campaign_id
- notice_no
- start_at
- end_at
- content_version
- published_at
- status

HrPublicNoticeEntry
- notice_id
- proposed_hire_id
- public_display_name
- public_fields_json
```

绝不直接把 Candidate 全字段暴露到公告。

## 13.5 异议

```text
HrNoticeObjection
- id
- notice_id
- proposed_hire_id nullable
- received_at
- source
- category
- content
- evidence
- status
- assignee
- resolution
- resolved_at
```

状态：

```text
RECEIVED
→ UNDER_REVIEW
→ NEEDS_EVIDENCE
→ RESOLVED_UPHOLD
→ RESOLVED_CHANGE
→ CLOSED
```

结果变化必须创建新决策版本。

## 13.6 Offer

```text
HrRecruitmentOffer
- id
- proposed_hire_id
- offer_no
- issued_at
- expires_at
- status
- accepted_at
- declined_at
- decline_reason
- document_id
- version
```

状态：

```text
DRAFT
→ APPROVED
→ ISSUED
→ VIEWED
→ ACCEPTED
   or DECLINED
   or EXPIRED
   or WITHDRAWN
```

## 13.7 HR05 Handoff

只有：

```text
ProposedHire APPROVED
+ PublicNotice CLOSED_NO_BLOCKER
+ Offer ACCEPTED（若学校流程要求）
+ PositionReservation VALID
```

才可：

```http
POST /api/hr/v1/recruitment/proposed-hires/{id}/handoff-to-hr05
Idempotency-Key: ...
```

产生：

```text
Hr05PendingOnboardingCreated
```

HR04 保存：

```text
handoff_id
handoff_at
hr05_case_id
```

重复调用必须返回同一 HR05 case，不得生成两份。

---

# 14. 招聘统一权威状态机

## 14.1 Application Canonical Status

冻结：

```text
DRAFT
SUBMITTED
UNDER_REVIEW
RETURNED
RESUBMITTED
QUALIFIED
DISQUALIFIED
ASSESSMENT_PENDING
ASSESSING
ASSESSMENT_PASSED
ASSESSMENT_FAILED
MEDICAL_PENDING
MEDICAL_REVIEW
BACKGROUND_PENDING
BACKGROUND_REVIEW
PROPOSED_HIRE
PUBLIC_NOTICE
OFFER_PENDING
OFFERED
OFFER_ACCEPTED
OFFER_DECLINED
HANDOFF_TO_HR05
WITHDRAWN
CANCELLED
```

## 14.2 Canonical Status 与 WorkflowStage 分离

```text
WorkflowStage:
“资格审查”
“笔试”
“试讲”
“学院面试”
“学校面试”
“体检”
“公示”
```

可以配置。

Canonical status 不允许学校随便创建。

## 14.3 Transition Ledger

```text
HrApplicationTransition
- id
- application_id
- from_status
- to_status
- action
- reason_code
- reason_text
- actor_id
- source
- occurred_at
- correlation_id
- workflow_stage_before
- workflow_stage_after
```

每次状态变化必须有 ledger。

---

# 15. 公共前端设计系统

继承 HR01/HR02/HR03，不允许 HR04 自造第三套视觉。

## 15.1 HR04 新增公共组件

```text
HrRecruitmentHeader
HrRecruitmentStatusBadge
HrRecruitmentFunnel
HrPlanCapacityCard
HrPositionReservationBadge
HrRecruitmentTimeline
HrApplicationStatusRail
HrCandidateAvatar
HrCandidateSummary
HrQualificationMatrix
HrQualificationRuleRow
HrEvidenceLink
HrMaterialVerificationPanel
HrReviewDecisionBar
HrAssessmentSchedule
HrExpertConflictBadge
HrScoreSheet
HrScoreLockBadge
HrCandidateCompare
HrPublicNoticeStatus
HrOfferStatus
HrRecruitmentRiskBanner
HrCandidatePortalStepper
```

## 15.2 视觉标准

建议延续“清透学院蓝 + 教育科技未来感”：

- 大面积白/浅灰蓝背景；
- 主色用于动作和信息，不用于所有卡片；
- 风险色只表达风险；
- 少渐变；
- 阴影克制；
- 卡片 12–16px radius；
- KPI 不超过首屏 5–6 个；
- 表格优先承载正式业务；
- 高密度页面必须有 sticky header；
- 资格矩阵/评分页优先横向可读；
- 禁止重要复杂录入使用通用右抽屉；
- 招聘公告、计划、资格规则采用独立页面；
- 候选详情可以使用 profile-layout，不做无限抽屉。

## 15.3 Public Portal 视觉

与管理员端共享 token，但视觉更简洁：

```text
学校 Logo / 招聘品牌
招聘公告
岗位卡
筛选
岗位详情
应聘进度
```

移动端 375px 必须作为正式验收。

---

# 16. 后端代码结构

不建议继续把所有逻辑堆到 `recruitment/views.py`。

建议：

```text
recruitment/
    legacy/                 # 原 Horilla 兼容代码逐步收拢

hr_recruitment/
    models/
        plan.py
        campaign.py
        candidate.py
        application.py
        qualification.py
        assessment.py
        selection.py
        offer.py
        notice.py
    services/
        plan_service.py
        campaign_service.py
        application_service.py
        qualification_service.py
        assessment_service.py
        offer_service.py
        handoff_service.py
        reservation_service.py
    selectors/
    policies/
    api/
    integrations/
        hr02.py
        hr03.py
        hr05.py
    projections/
        horilla_recruitment.py
        horilla_candidate.py
        horilla_stage.py
    jobs/
    tests/
```

若为降低改造风险暂不拆 Django app，也必须按上述 service/selectors/policy/projection 分层，禁止新逻辑继续塞进单个 `views.py`。

---

# 17. API 总合同

基路径：

```text
/api/hr/v1/recruitment/*
```

所有 response：

```json
{
  "apiVersion": "v1",
  "schemaVersion": "hr04.1",
  "requestId": "uuid",
  "data": {}
}
```

## 17.1 Breaking Change

V1：

- 只新增字段；
- 不删除已有字段；
- 不改变已有字段类型；
- enum 新增值前端必须 graceful fallback；
- 删除/改类型必须 `/v2/`。

## 17.2 写 API

必须接受：

```text
Idempotency-Key
If-Match / version
```

关键业务冲突：

```text
409 VERSION_CONFLICT
409 POSITION_CAPACITY_CONFLICT
409 INVALID_STATE_TRANSITION
409 SCORE_ALREADY_LOCKED
409 APPLICATION_ALREADY_SUBMITTED
```

## 17.3 错误信封

```json
{
  "apiVersion": "v1",
  "requestId": "...",
  "error": {
    "code": "QUALIFICATION_RULE_VERSION_MISMATCH",
    "message": "资格条件版本已发生变化，请刷新后重试",
    "details": {}
  }
}
```

---

# 18. 数据新鲜度

继承 HR01：

```text
sourceUpdatedAt
calculatedAt
maxStaleSeconds
hardExpireSeconds
status:
OK / PARTIAL / STALE / UNAVAILABLE / ERROR
```

应用于：

- 招聘漏斗；
- vacancy/reservation；
- 报名人数；
- 待审人数；
- 选拔进度；
- HR01 招聘摘要。

Position capacity 推荐短时缓存或强一致实时查询，正式录用动作绝不能依赖缓存。

---

# 19. 通知体系

事件：

```text
PLAN_RETURNED
PLAN_APPROVED
CAMPAIGN_PUBLISHED
APPLICATION_SUBMITTED
APPLICATION_RETURNED
APPLICATION_QUALIFIED
APPLICATION_DISQUALIFIED
ASSESSMENT_SCHEDULED
ASSESSMENT_CHANGED
PUBLIC_NOTICE_STARTED
OBJECTION_RECEIVED
OFFER_ISSUED
OFFER_EXPIRING
OFFER_ACCEPTED
HANDOFF_CREATED
```

渠道：

- 站内；
- 邮件；
- 短信（接入后）；
- 微信/企业微信（未来适配）。

每条通知必须：

- tenant；
- business object；
- recipient；
- template version；
- send status；
- retry；
- audit。

---

# 20. 材料与文件安全

候选材料：

```text
身份证明
学历
学位
职称
教师资格
技能证书
工作经历证明
代表成果
招聘要求的其他材料
```

必须：

- private object storage；
- 短期签名 URL；
- 防双扩展名；
- MIME 检查；
- 文件大小；
- malware scan；
- SHA-256；
- version；
- access log；
- watermarked preview（按配置）；
- export 打包走异步任务；
- 不把真实存储路径暴露给浏览器。

---

# 21. Excel / 批量处理

正式要求：

```text
模板下载
→ 上传
→ 文件结构预检
→ staging
→ 业务校验
→ 错误统计
→ 错误工作簿
→ 用户确认
→ 异步执行
→ progress
→ completed/failed
→ audit
```

允许场景：

- 历史人才库导入；
- 线下报名迁移；
- 专家名单；
- 评分导入（严格权限/锁定）；
- 体检/考察结论批量回填；
- 录用结果历史迁移。

公开正常招聘优先 candidate portal，不鼓励管理员代报名。

---

# 22. 数据隐私与公平性

## 22.1 最小采集

报名阶段只采岗位所需信息。

不因“未来也许会用”提前收集：

- 银行卡；
- 详细家庭成员；
- 无关健康信息。

## 22.2 敏感字段服务端裁剪

角色：

```text
Recruiter
Qualification Reviewer
Expert
Hiring Manager
Auditor
```

看到不同字段。

## 22.3 AI 使用红线

未来若引入 AI：

允许：

- 材料分类；
- 简历结构化；
- 缺材料提示；
- 规则预检解释；
- 面试纪要摘要。

禁止：

- 黑箱自动最终淘汰；
- 根据敏感属性推断候选适配；
- 不可解释排序决定最终录用；
- 用历史偏差训练结果直接代替人工结论。

所有 AI 结果：

```text
advisory only
source documented
human review required
```

---

# 23. 搜索与去重

Candidate 普通搜索：

- 姓名；
- candidate_no；
- email；
- phone（按权限）；
- 专业；
- 学历；
- 招聘项目；
- 应聘岗位。

高敏 exact match：

```http
POST /api/hr/v1/recruitment/candidates/identity-match
```

仅特权用户。

去重结果：

```text
EXACT_MATCH
POSSIBLE_MATCH
NO_MATCH
INSUFFICIENT_DATA
```

禁止自动 merge。

---

# 24. 评分与排名

总分：

```text
final_score = Σ normalized_component_score × weight
```

服务端计算。

必须保存：

```text
selection_scheme_version
component raw score
normalized score
weight
calculation version
calculated_at
```

排名不是简单动态 ORDER BY。

结果冻结时生成：

```text
HrSelectionResultSnapshot
```

后续规则变化不能改变已冻结排名。

---

# 25. 事务与并发

必须覆盖：

## 25.1 同时提交 Application

Idempotency-Key + unique constraint。

## 25.2 同一岗位最后一个名额

事务锁 HR02 reservation/capacity。

## 25.3 两个人同时审核一个申请

optimistic lock/version。

## 25.4 专家重复提交评分

唯一：

```text
event + candidate + evaluator + active_sheet
```

## 25.5 Offer 接受重复点击

幂等。

## 25.6 HR05 handoff

幂等 + unique proposed_hire。

---

# 26. 审计

必须审计：

- 计划创建/修改/批准；
- 招聘公告发布和 amendment；
- 条件规则变化；
- Application 提交/撤回；
- 资格结论；
- 评分提交/解锁；
- 专家回避；
- 体检/考察结论；
- 拟录用；
- 公示；
- 异议；
- Offer；
- HR05 handoff；
- 候选敏感信息查看；
- 简历/身份证材料下载；
- Excel 导出。

正式：

```text
HrRecruitmentAuditEvent
SensitiveCandidateAccessLog
```

不能只依赖 Horilla simple-history。

---

# 27. 数据质量

指标：

```text
无HR02岗位映射的招聘岗位
reservation缺失
公告已发布但无qualification version
Application缺candidate
SUBMITTED缺submission timestamp
QUALIFIED无decision
DISQUALIFIED无reason
Assessment score未锁
ProposedHire超过岗位额度
PublicNotice结束但未关闭
Offer accepted未handoff
HR05 handoff重复
```

HR01 可显示 HR04 数据质量警告，但不显示虚假 0。

---

# 28. Horilla Legacy Mapping

施工 S0 必须生成：

```text
docs/hr04/LegacyRecruitmentMapping.md
```

最低映射：

| Horilla | 新 HR04 | 处理 |
|---|---|---|
| Recruitment | HrRecruitmentCampaign | legacy projection |
| Recruitment.vacancy | HrRecruitmentPosition + HR02 reservation | 不再权威 |
| Recruitment.open_positions | HrRecruitmentPosition | 映射 |
| Stage | WorkflowStage projection | 不再权威 canonical state |
| Candidate | Candidate + Application legacy projection | 拆分 |
| Candidate.stage_id | Application.workflow_stage | projection |
| Candidate.hired | ProposedHire/Handoff | 不再权威 |
| RejectedCandidate | Qualification/selection decision | 按原因迁移 |
| RecruitmentSurvey | ApplicationForm/Survey | ADAPT |
| InterviewSchedule | HrAssessmentEvent | ADAPT |
| CandidateDocument | HrApplicationMaterial | ADAPT |
| LinkedInAccount | Optional integration | 默认关闭 |

---

# 29. Legacy 退出合同

模式：

```text
LEGACY_RECRUITING_ONLY
→ DUAL_READ_COMPARE
→ HR04_AUTHORITY
```

## 29.1 LEGACY_RECRUITING_ONLY

Horilla 继续主用，新 HR04 可只读影子建模。

## 29.2 DUAL_READ_COMPARE

新旧同时计算：

- campaign；
- applications；
- candidate counts；
- stage mapping；
- hired；
- interview。

生成 discrepancy report。

禁止自动取“哪边有值用哪边”。

## 29.3 HR04_AUTHORITY

进入后：

- 新业务只写 HR04；
- Horilla 只做 projection；
- Pipeline UI 从 projection 渲染；
- 禁止 provider 故障自动 fallback legacy；
- 回滚必须是受控 runbook，不是代码里的自动逻辑。

---

# 30. 数据迁移策略

## 30.1 Candidate 拆分

Legacy Candidate：

```text
Candidate A (email + Recruitment1)
Candidate B (同email + Recruitment2)
```

迁移：

```text
Candidate Person 1
├ Application 1
└ Application 2
```

但不得仅凭 email 自动合并。

匹配：

```text
tenant
+ verified identity hash（优先）
+ email/mobile
+ name
```

POSSIBLE_MATCH 进入人工队列。

## 30.2 Stage Mapping

建立显式配置：

```text
LegacyStageMap
legacy_stage_id
→ canonical_status
→ workflow_stage
```

迁移前必须覆盖所有 active stage。

---

# 31. 性能指标

建议生产验收：

- 招聘项目列表 p95 < 500ms；
- Application 列表 p95 < 700ms；
- Qualification 工作台切人 < 300ms cached / <700ms cold；
- Pipeline 500 applications 可流畅操作；
- 人才库 10万候选数据分页查询 p95 < 800ms；
- public application submit p95 < 1.5s（不含大附件上传）；
- 评分保存 p95 < 500ms；
- dashboard 不允许 N+1；
- 导出 > 5000 行走异步；
- 文件打包走异步；
- 大批资格预检走后台 job。

所有数字可在真实容量测试后调整，但禁止无指标。

---

# 32. 可观测性

metrics：

```text
hr04_application_submitted_total
hr04_qualification_pending
hr04_qualification_returned_total
hr04_assessment_submission_total
hr04_offer_accepted_total
hr04_handoff_failed_total
hr04_position_capacity_conflict_total
hr04_legacy_discrepancy_total
```

日志：

- requestId；
- tenant；
- actor；
- campaign/application；
- action；
- duration；
- error code。

禁止输出候选人敏感明文。

---

# 33. 安全测试矩阵

必须验证：

- 学校A无法访问学校B招聘；
- 学院A无法访问学院B候选人；
- Expert 只能访问 assigned；
- Candidate A 不可访问 Candidate B；
- public slug 不可枚举内部 ID；
- IDOR；
- 简历下载越权；
- 身份证 exact search 权限；
- 导出权限；
- 评分解锁权限；
- 公示发布权限；
- HR05 handoff 权限；
- malicious upload；
- double extension；
- XSS；
- CSRF；
- rate limiting；
- brute force；
- public application duplicate submission。

---

# 34. 测试体系

每个三级模块：

```text
model tests
service tests
policy tests
API tests
state-machine tests
tenant-isolation tests
data-scope tests
idempotency tests
transaction tests
concurrency tests
audit tests
migration tests
projection tests
UI E2E
accessibility
visual regression
```

---

# 35. HR04-01 验收

必须：

- 创建年度计划；
- 学院提交需求；
- HR02 容量显示正确；
- RETURNED 可修改重提；
- REJECTED 不可直接重提；
- 批准时并发重检；
- 跨学院 scope 正确；
- Excel 正确；
- 审计完整。

---

# 36. HR04-02 验收

必须：

- 从 approved plan 创建 campaign；
- 创建多个 recruitment positions；
- reservation 正确；
- 发布公告产生 immutable version；
- amendment 不覆盖旧 version；
- 关闭招聘释放未使用 reservation；
- Horilla projection 正确；
- Pipeline 可正常显示。

---

# 37. HR04-03 验收

必须：

- 同一候选人可有多个 Application；
- 不以 email 自动错误合并；
- portal draft；
- submit 幂等；
- candidate self scope；
- 高敏字段裁剪；
- 材料版本；
- 历史应聘完整。

---

# 38. HR04-04 验收

必须：

- 条件版本锁定；
- 系统预检；
- RETURNED；
- RESUBMITTED；
- QUALIFIED；
- DISQUALIFIED；
- 手工 override 有 reason；
- 规则变化不重写旧申请；
- 审核人数据范围正确；
- 审核队列跨页准确。

---

# 39. HR04-05 验收

必须：

- 多种 component；
- 权重合计；
- 专家分配；
- 回避；
- 排期冲突；
- 盲评；
- 服务端评分；
- score lock；
- reopen；
- tie-break；
- 结果 snapshot；
- 体检/考察敏感隔离。

---

# 40. HR04-06 验收

必须：

- 拟录用不超额度；
- 公示；
- 异议；
- 结果变更版本；
- Offer；
- Accepted；
- Expired；
- HR05 handoff；
- handoff 幂等；
- 未公示完成时禁止 handoff；
- reservation 提交/释放正确。

---

# 41. 前端 E2E 验收

四档：

```text
1440 desktop
1280 laptop
768 tablet
375 mobile/public portal
```

场景：

1. 学院提交计划；
2. 人事批准；
3. 创建招聘项目；
4. 发布岗位；
5. 候选人手机报名；
6. 上传材料；
7. HR 退回补件；
8. 候选人补交；
9. 资格通过；
10. 排试讲；
11. 专家盲评；
12. 成绩锁定；
13. 拟录用；
14. 公示；
15. Offer；
16. handoff HR05。

不得只测试 happy path。

---

# 42. Accessibility

至少 WCAG 2.1 AA 思路：

- 键盘完成报名；
- focus visible；
- 表单 error 可读；
- 图标有文本；
- 状态不用颜色单独表达；
- Pipeline 卡片 drag/drop 必须有键盘替代；
- 评分表 screen reader label；
- public portal 375px 无横向爆版；
- PDF/材料预览有下载替代；
- 弹窗 focus trap 正确。

---

# 43. Visual Regression

重点截图：

- 招聘控制台；
- 招聘项目详情；
- 岗位详情；
- Candidate profile；
- Application detail；
- 资格审核矩阵；
- 专家评分；
- 拟录用；
- 公示；
- public job detail；
- public application form；
- empty/error/stale/permission states。

---

# 44. 公共组件验收

禁止 HR04 页面内复制 500 行 CSS。

组件必须：

- token 驱动；
- light/dark（若产品保留 dark）；
- responsive；
- skeleton；
- empty；
- error；
- permission-denied；
- stale；
- tooltip；
- consistent spacing。

---

# 45. API 契约测试

要有 schema contract tests。

验证：

- apiVersion；
- schemaVersion；
- additive field compatibility；
- enum fallback；
- error code；
- requestId；
- pagination；
- sort；
- filters；
- idempotency；
- If-Match/version。

---

# 46. 数据库约束

关键 DB 级约束：

- tenant FK 一致；
- application_no tenant unique；
- active duplicate application policy；
- campaign code tenant unique；
- score evaluator+candidate+event unique；
- position reservation reference unique；
- offer no unique；
- handoff proposed_hire unique；
- version >= 1；
- planned/approved counts non-negative。

不能全靠 Python clean。

---

# 47. 索引

至少考虑：

```text
(tenant_id, status)
(tenant_id, campaign_id, status)
(tenant_id, recruitment_position_id, canonical_status)
(tenant_id, candidate_id)
(tenant_id, application_no)
(tenant_id, submitted_at)
(tenant_id, due_at)
(event_id, application_id)
(proposed_hire_id, status)
```

PostgreSQL 根据真实查询计划优化。

---

# 48. 列表分页与筛选

所有列表：

```text
WHERE
→ COUNT
→ ORDER
→ OFFSET/LIMIT or cursor
```

禁止：

```text
先分页
→ Python过滤
```

过滤必须数据库层完成。

大人才库可考虑 cursor pagination。

---

# 49. 公开报名可靠性

候选提交：

1. save draft；
2. upload materials；
3. validate required；
4. submit transaction；
5. generate application no；
6. freeze referenced versions；
7. emit outbox event；
8. acknowledgement notification。

网络重试不得产生双申请。

---

# 50. Outbox/Event

关键事件：

```text
HiringPlanApproved
RecruitmentCampaignPublished
ApplicationSubmitted
QualificationReturned
QualificationFinalized
AssessmentResultLocked
ProposedHireApproved
PublicNoticeClosed
OfferAccepted
RecruitmentHandoffCreated
```

transactional outbox。

---

# 51. 不可变性

一旦正式：

- 公告 published version immutable；
- qualification rule locked version immutable；
- selection scheme locked version immutable；
- submitted Application 原始快照不可静默改；
- locked score 不可直接改；
- final selection snapshot 不可直接改；
- public notice version 不可直接改；
- accepted offer 不可直接改。

修改走新 version / correction。

---

# 52. 配置边界

可以配置：

- 流程阶段；
- 岗位允许的 selection components；
- 评分权重；
- 招聘材料；
- 资格规则模板；
- 公示周期；
- Offer 期限；
- 是否允许同批多岗位；
- 数据保留周期。

不能配置掉：

- tenant isolation；
- canonical status 核心语义；
- audit；
- version；
- idempotency；
- score lock；
- position capacity control；
- sensitive field policies；
- HR05 handoff 前置条件。

---

# 53. AI 施工顺序

编码 AI 收到整份总册后，必须先输出任务树，不允许立即大改。

## HR04-S0 基线复审

只读：

```text
recruitment/models.py
recruitment/urls.py
recruitment/forms.py
recruitment/views/*
recruitment/cbv/*
recruitment/templates/*
onboarding/*
employee/*
base/*
horilla_documents/*
horilla_audit/*
```

输出：

```text
HR04_GAP_MATRIX.md
LegacyRecruitmentMapping.md
HR04_TASK_TREE.md
HR04_RISK_REGISTER.md
```

**S0 不得做大规模业务改造。**

## HR04-S1 契约/公共组件

- 权限；
- enum；
- API envelope；
- UI components；
- route skeleton；
- projection contracts。

## HR04-S2 权威模型骨架

- plan；
- campaign；
- candidate/application；
- qualification；
- assessment；
- proposed hire/offer；
- migrations；
- DB constraints。

## HR04-S3 HR04-01

年度用人计划完整闭环。

## HR04-S4 HR04-02

招聘项目/岗位 + HR02 reservation + announcement version。

## HR04-S5 HR04-03

Candidate/Application + public portal。

## HR04-S6 HR04-04

资格审查 + rule engine + RETURNED。

## HR04-S7 HR04-05

考试面试 + scoring + conflict + lock。

## HR04-S8 HR04-06

拟录用 + 公示 + Offer + HR05 handoff。

## HR04-S9 Legacy Projection

把 Horilla Recruitment/Stage/Candidate 映射到新 authority。

## HR04-S10 DUAL_READ_COMPARE

迁移旧数据、差异报告。

## HR04-S11 生产级验收

- security；
- performance；
- concurrency；
- E2E；
- accessibility；
- visual；
- migration rollback。

## HR04-S12 封板

只有全部绿：

```text
HR04 READY FOR ACCEPTANCE
```

---

# 54. AI 禁止越界清单

AI 不得：

- 顺手重写 HR02；
- 顺手重写 HR03；
- 把 HR05 做进 HR04；
- 删除 Horilla recruitment before migration；
- 直接 rename tables 冒充迁移；
- 改 main；
- 跳过 migration；
- 用假数据让 UI 好看；
- 用 mock endpoint 冒充完成；
- 关闭 permission 解决 403；
- 把 Stage 名称当业务状态；
- 把 Candidate.hired 当最终录用真相；
- 自动把 Candidate 转 Employee；
- 为了 CI 绿跳过测试；
- 降低安全测试；
- 同步大导出；
- 公开材料裸 URL。

---

# 55. 施工提交边界

推荐一个三级模块一个可审 PR/commit phase。

每阶段：

```text
migration
model/service
API
UI
tests
docs
```

不要 100 个文件一口气改完才测试。

---

# 56. 自纠错与遗漏检查

本总册在最终冻结前主动检查以下易漏点：

## 56.1 Candidate ≠ Application

已补。

## 56.2 RETURNED ≠ DISQUALIFIED

已补，且写入状态机。

## 56.3 公告和规则版本

已补。

## 56.4 Position 超卖

已通过 HR02 Reservation 补。

## 56.5 录用 ≠ 入职

已通过 HR05 handoff 补。

## 56.6 专家回避

已补。

## 56.7 评分锁定与解锁审计

已补。

## 56.8 体检信息高敏

已补。

## 56.9 公示异议

已补独立 case。

## 56.10 Candidate retention

已补。

## 56.11 多岗位报名

已改为学校 policy。

## 56.12 外部 portal tenant 解析

已明确由 public slug/token 解析，不允许裸 tenant id。

## 56.13 AI 自动筛选风险

已设 advisory-only 红线。

## 56.14 招聘规则中途修改

已用 version + amendment 处理。

## 56.15 历史结果被重新计算

已通过 result snapshot/locked scheme 处理。

## 56.16 Horilla Pipeline 复用与权威状态冲突

已用 projection 分层处理。

## 56.17 同一人多次招聘历史

已通过 Candidate/Application 分离。

## 56.18 公开公示泄露

已建立 PublicNoticeEntry 可发布字段白名单。

## 56.19 HR03 person 跨学校隐式关联

HR04 Candidate 为 tenant-private，不跨校合并。

## 56.20 浏览器返回/网络重试双提交

已加入 idempotency。

---

# 57. 终极封板条件

HR04 只有同时满足以下条件，才允许“封板”：

### 业务

- 六个三级模块全闭环；
- 用人计划→招聘→报名→资格→选拔→拟录用→公示→Offer→HR05 通；
- RETURNED/不合格/撤回语义正确；
- 不超岗位额度；
- 不生成重复 HR05 Case。

### 数据

- Candidate/Application 分离；
- 规则/公告/评分方案版本化；
- 正式结果不可变；
- Legacy 完成 mapping；
- 新旧对账达到门槛。

### 安全

- tenant isolation；
- data scope；
- candidate self；
- expert assignment；
- sensitive field；
- document security；
- audit 全绿。

### 技术

- migrations；
- API contract；
- idempotency；
- concurrency；
- async jobs；
- outbox；
- observability；
- backup/restore 影响已验证。

### 前端

- 6 个工作区 UI 完整；
- public portal 完整；
- 375/768/1280/1440；
- accessibility；
- visual regression；
- empty/error/stale/partial 权威状态。

### 迁移

- `HR04_AUTHORITY` 切换演练；
- 禁止自动 fallback legacy；
- rollback runbook；
- discrepancy report 可审。

最终允许输出：

```text
HR04 READY FOR ACCEPTANCE
```

否则只能输出：

```text
HR04 NOT READY
blocking:
- ...
```

---

# 58. 最终架构冻结图

```text
HR02
组织 / 岗位 / 编制 / Position Reservation
                │
                ▼
HR04-01 年度用人计划
                │
                ▼
HR04-02 招聘项目与岗位
                │
                ├────────────┐
                ▼            │
        招聘公告 / 规则版本   │
                │            │
                ▼            │
HrRecruitmentCandidate       │
        │                     │
        └─ HrJobApplication  │
                │            │
                ▼            │
HR04-04 资格审查             │
                │            │
                ▼            │
HR04-05 考试面试与考察       │
                │            │
                ▼            │
HR04-06 拟录用 / 公示 / Offer│
                │            │
                ▼            │
           HR05 Handoff      │
                │            │
                ▼            │
              HR05           │
                │            │
                ▼            │
              HR03 ◄─────────┘
       正式人员事实生效
```

Horilla：

```text
Recruitment
Stage
Candidate
Interview
Survey
Document
Pipeline
      │
      ▼
Legacy Adapter / Projection
      │
      ▼
HR04 权威领域
```

**最终原则：**

> **Horilla 给我们一副已经能跑、能看、能操作的招聘骨架；跃科 HR04 的任务不是把它推倒，而是把“高校计划、岗位额度、Candidate/Application、资格事实、专业选拔、公示、Offer、HR05 handoff”这些真正决定商业级可靠性的业务真相补进去，并让旧 Pipeline 最终成为新权威事实的高质量工作界面。**

---

# 59. 外部资料复核门

施工 S0 必须再次核验最新官方资料，因为成熟 HCM 产品功能会持续变化：

- Workday Recruiting / Talent Acquisition 官方产品资料；
- SAP SuccessFactors Recruiting 官方产品资料；
- Oracle Recruiting Cloud 官方产品资料；
- 目标客户所在省份/学校最新公开招聘政策、事业单位招聘规定和学校招聘公告；
- 学校内部人事制度与公示/体检/考察/备案流程。

本总册冻结的是**架构和生产级业务合同**；具体招聘条件、年龄、专业目录、考试权重、公示天数等不得写死为全国统一规则，必须按学校政策配置和版本化。

---

# 60. 编码 AI 首条执行指令

将整份总册交给 AI 后，第一条执行要求固定为：

```text
读取《04_HR04_招聘与人才引进_施工总册_终极版.md》。

先不要修改业务代码。

完成 HR04-S0：
1. 逐目录审计当前 Horilla recruitment/onboarding/employee/base/documents/audit 相关代码；
2. 逐模型输出 KEEP / ADAPT / LEGACY_PROJECTION / NEW / REMOVE-LATER；
3. 建立 LegacyRecruitmentMapping；
4. 对照总册六个三级模块输出真实 Gap Matrix；
5. 检查 A0、HR02、HR03、HR05 依赖是否满足；
6. 输出 S1-S12 文件级任务树；
7. 标记 P0 数据/权限/状态机/并发风险；
8. 不合并 main，不删除 Horilla legacy，不用 mock 冒充业务完成。

S0 报告通过复审后，再按 S1 → S12 顺序逐阶段施工。
每阶段必须跑对应测试并报告真实结果。
```

---

**文档状态：V1.0 终极冻结版。**
