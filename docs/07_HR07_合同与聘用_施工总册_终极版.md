# 07_HR07_合同与聘用_施工总册（终极冻结版）

> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API（`/api/v1/hr`）、数据库目标（MySQL-only）、事件、权限、Legacy、审计、安全和最终生产 Gate。

> 产品：跃科高校人事管理与教师发展系统  
> 二级模块：HR07 合同与聘用  
> 三级模块数量：5  
> 总体接管策略：REWRITE  
> 版本：V1.0 终极冻结版  
> 文档性质：HR07 唯一权威施工事实源；可直接整份交给编码 AI 执行“Horilla Contract/Payroll 基线复审 → Legacy 合同映射 → 合同领域重构 → 模板与规则 → 签订/续签 → 变更/解除 → 聘期/到期预警 → 电子签/档案 → HR03/HR05/HR06/HR15/HR16 联动 → Legacy Projection → 双读对账 → 测试 → 封板”的生产级施工。  
> 适配底座：Horilla HRMS 2.0（当前 `penghaibin9/renshi` 基线）  
> 前置标准：继承《01_HR01》《02_HR02》《03_HR03》《04_HR04》《05_HR05》《06_HR06》终极版的 A0 多学校 fail-closed、API 版本化、错误信封、公共 UI、数据新鲜度、Legacy 退出、异步任务、审计、可观测性、Excel、敏感字段、幂等、事务、Outbox、版本冻结和 AI 施工纪律。  
> 强依赖：HR03 `EmploymentRelationship` 是“人与学校聘用关系”的权威事实；HR07 **不得再建第二套 EmploymentRelationship**。HR07 管理的是“该聘用关系下签署了哪些合同/协议、版本、条款、审批、签署、续签、变更、解除和风险”。  
> 编写日期：2026-08-08  
> 核心原则：**合同不是一行 start/end/status；正式合同一旦签署，内容不可被静默覆盖。续签、补充协议、变更、解除、终止都必须形成新的法律/业务事实。**

---

# 0. 最终三级模块冻结

沿用产品总设计中已经冻结的三级模块名称，不在 HR07 施工阶段改菜单：

```text
HR07 合同与聘用
├─ HR07-01 合同台账
├─ HR07-02 合同模板与规则
├─ HR07-03 签订与续签
├─ HR07-04 变更与解除
└─ HR07-05 聘期与到期预警
```

五个工作区职责：

- **HR07-01 合同台账**：查看“谁、哪种聘用关系、有哪些主合同/补充协议、当前有效版本是什么、历史是什么”；
- **HR07-02 合同模板与规则**：管理合同类型、模板版本、条款变量、适用范围、编号规则、续签/期限/签署/附件规则；
- **HR07-03 签订与续签**：新签、续签、合同评审、审批、生成、签署、归档、生效；
- **HR07-04 变更与解除**：补充协议、合同变更、中止/恢复、解除、终止、撤销、更正；
- **HR07-05 聘期与到期预警**：合同/聘期/试用/附件/签署到期风险、续聘决策、逾期闭环和风险分析。

---

# 1. 结论先行

HR07 不是 Payroll 下的一张 `Contract` 表。

它是：

> **Employment Agreement & Contract Lifecycle Management：把聘用关系的法律文件、版本、规则、审批、签署、履约期限、续聘决策、解除终止和证据完整管理起来。**

高校场景的完整事实链：

```text
HR05 正式入职 / HR03 EmploymentRelationship
                    │
                    ▼
             确认合同适用规则
                    │
                    ▼
              选择合同模板版本
                    │
                    ▼
             生成 Agreement Draft
                    │
                    ▼
              条款核验 / 审批
                    │
                    ▼
               合同文件生成
                    │
                    ▼
              线下签署 / 电子签
                    │
                    ▼
            SIGNED_WAITING_EFFECTIVE
                    │
             到达 effective_from
                    ▼
                  ACTIVE
                    │
      ┌─────────────┼─────────────────┐
      │             │                 │
    续签         补充/变更           解除/终止
      │             │                 │
      ▼             ▼                 ▼
 新周期/新版本   Amendment Event   Termination Event
      │             │                 │
      └─────────────┴─────────────────┘
                    ▼
              历史不可变档案
```

HR07 必须能回答：

1. 这个人与学校当前是什么聘用关系？——引用 HR03；
2. 这个聘用关系当前有哪些有效合同/协议？
3. 这份合同采用的是哪个模板版本？
4. 当时签署的正文到底是什么，今天模板改了是否会污染历史？
5. 谁审批、谁签署、什么时候签署？
6. 签署日、合同生效日、到期日、解除日是否明确区分？
7. 是续签、延期、补充协议、业务变更还是数据纠错？
8. 何时应该开始续聘评估，而不是到期当天才发现？
9. HR06 异动是否触发合同复核？
10. HR16 离职/退休是否已经正确结束合同？
11. HR15 薪酬变化是合同约定还是实际发放，是否被错误混在一起？
12. 电子签平台失败时，人事事实是否仍可解释和恢复？
13. 合同附件、签署件、补充协议、审批记录是否形成一条证据链？
14. 合同已经过期但学校仍未续签/终止时，系统是否能真正告警而不是只发一封邮件？

---

# 2. 本总册主动纠错：HR07 不重复创建 EmploymentRelationship

早期草案容易犯一个架构错误：

```text
HR03 有 EmploymentRelationship
HR07 又建 EmploymentRelationship
```

这会产生双真值。

最终冻结：

```text
HR03:
HrPerson
HrStaffMaster
HrEmploymentRelationship    ← 聘用关系权威
HrAssignment

HR07:
HrAgreement                 ← 合同/聘用协议权威
HrAgreementVersion
HrAgreementTerm
HrAgreementEvent
HrAgreementDocument
HrSignatureEnvelope
...
```

HR07 只引用：

```text
employment_relationship_id
```

不得复制一份“聘用状态”。

---

# 3. 三家成熟 HCM 对标：共同精华

## 3.1 Workday Employee Contracts

当前 Workday 官方合同能力体现：

- 支持 fixed-term 与 open-ended employee contracts；
- 合同不是独立孤岛，而与 Staffing/Business Process/security/downstream impact 联动；
- 可以生成合同文件并让员工查看；
- fixed-term contract 可设 review date；
- Review Employee Contracts 可决定 renew / end / change job 等动作；
- 可配置最大累计合同期限、最大续签次数等规则；
- 一个 job 在同一时间只允许一个 active contract；
- Change Job 等业务过程可包含结束旧合同、建立新合同步骤；
- Contract ID 可保持同一 employment 下连续性。

跃科吸收：

```text
Agreement Rule
Review Date
Renewal Policy
Contract ID Continuity
Business Process Integration
```

但不照搬 “one contract per job” 作为全国高校硬规则；我们用 `AgreementFamily + overlap_policy` 参数化。

## 3.2 SAP SuccessFactors Employee Central

SAP 当前实践强调：

- contract type / contract end date 属于 Employment/Job Information 的正式业务数据；
- fixed-term contract 接近到期可提前自动 alert；
- manager + HR 可以收到 Take Action；
- 合同到期后仍未处理可再次升级提醒；
- contract extension 可通过 event reason + workflow 执行；
- business rule 可检查 fixed-term 合同必须有 end date；
- extension 可以有国家/地区规则，如最大期限；
- termination、contract end、position follow-up、documents 等能形成业务流程。

跃科吸收：

```text
AgreementType
EventReason
Rule Engine
Workflow
Escalating Alert
Take Action
```

## 3.3 Oracle Fusion Cloud HCM

Oracle 当前合同设计强调：

- Contract 与 Assignment / Work Relationship 关联；
- 支持 contract type、duration、start/end；
- extension 有明确 history；
- effective-dated update 与 correction 语义不同；
- extension 和 assignment 的日期关系有严格约束；
- contract 更新不能随意破坏 future record；
- 合同与 employment terms / assignment 的 effective date 需要保持一致性；
- 可从 Employment Contracts 管理现有合同。

跃科吸收：

```text
Effective-dated Terms
Extension History
Update ≠ Correction
Future Record Conflict
Assignment/Employment Alignment
```

## 3.4 三家共同精华冻结

HR07 必须具备：

1. 合同依附正式聘用关系，不是独立 Employee 附件；
2. 固定期限 / 无固定期限 / 协议类可配置；
3. 合同编号连续性；
4. 合同模板和合同正文分离；
5. 模板、条款、规则全部版本化；
6. 已签署正文不可覆盖；
7. 新签、续签、变更、解除属于不同业务动作；
8. 合同有 review date，而不只 end date；
9. 到期预警必须可行动、可升级；
10. effective-dated update 与 correction 分离；
11. future contract records 必须冲突检测；
12. 合同与 HR03 Employment/Assignment 事实要对账；
13. 权限/流程/电子签/文件证据必须统一。

---

# 4. 中国高校制度校正

高校岗位聘用制度通常要求：

- 区别不同类型、不同层次受聘人员；
- 可采用短期、中期、长期等不同合同；
- 合同应明确岗位职责、工作条件、工资福利、岗位纪律、变更/解除/终止条件、聘用期限等；
- 岗位调整时，合同相关内容需要相应变更；
- 合同期满前，应结合履职/考核及时作出续聘、岗位调整或解聘决定；
- 某些人员存在事业单位聘用合同、劳动合同、劳务/外聘协议、人才引进协议、补充协议等多份法律/管理文件并存。

因此系统必须支持：

```text
一个 HR03 EmploymentRelationship
    ├─ 主聘用合同
    ├─ 补充协议
    ├─ 人才引进协议
    ├─ 保密/知识产权协议（按学校配置）
    └─ 其他附属协议
```

不能继续坚持：

> “一个员工只能有一个 active Contract”。

---

# 5. Horilla 2.0 Contract 真实代码审计结论

当前 Horilla `Contract` 位于 Payroll 领域。

它的字段包含：

```text
contract_name
employee
contract_start_date
contract_end_date
wage_type
pay_frequency
wage
filing_status
contract_status
department
job_position
job_role
shift
work_type
notice_period
contract_document
leave deduction settings
note
history
```

当前状态仅：

```text
draft
active
expired
terminated
```

并且当前实现存在几个关键耦合：

1. 保存时会从 `EmployeeWorkInformation` 自动补 department / position / role / work type / shift；
2. end_date 早于 `date.today()` 会自动标记 expired；
3. 一个 employee 最多一个 active contract；
4. 一个 employee 最多一个 draft contract；
5. active contract 的 wage 会尝试写回 `EmployeeWorkInformation.basic_salary`；
6. 合同模型同时承载 Payroll/Leave 计算配置；
7. 合同和 Employee 当前快照强绑定；
8. 缺少 agreement family、模板版本、审批、签署、renewal、amendment、termination event、review decision 等正式领域事实。

结论：

```text
Horilla Contract model         REWRITE
Horilla Contract list/detail   ADAPT
Horilla document UI            ADAPT
Horilla payroll linkage        DECOUPLE
Horilla wage/leave settings    MOVE TO HR15/HR11
Horilla history                TECHNICAL ONLY
```

---

# 6. HR07 的核心 REWRITE 原则

不删除 Horilla 旧合同立即重做。

采用 Strangler：

```text
HR07 Authority
       ↓
Legacy Contract Projection
       ↓
旧 Payroll / 页面兼容
```

最终旧 `Contract` 只服务：

- 老 Payroll 模块兼容；
- 过渡查询；
- 旧页面 redirect；
- Legacy comparison。

不再作为合同权威。

---

# 7. HR07 权威领域模型总览

```text
HR03 HrEmploymentRelationship
              │
              ▼
         HrAgreement
        /     |      \
       /      |       \
AgreementVersion   AgreementEvent
       |                |
       |                ├─ RENEW
       |                ├─ AMEND
       |                ├─ SUSPEND
       |                ├─ RESUME
       |                ├─ TERMINATE
       |                └─ VOID/CORRECT
       |
       ├─ AgreementTerm[]
       ├─ AgreementDocument[]
       ├─ ApprovalSnapshot
       ├─ SignatureEnvelope[]
       ├─ AgreementEffectiveSnapshot
       ├─ RenewalReview[]
       └─ Risk / Alert[]
```

配置域：

```text
AgreementType
AgreementFamily
AgreementTemplate
AgreementTemplateVersion
AgreementClauseDefinition
AgreementRuleSet
AgreementNumberRule
AgreementWorkflowPolicy
AgreementAlertPolicy
AgreementRetentionPolicy
```

---

# 8. Agreement Family：解决“一人多协议”

推荐内置：

```text
PRIMARY_EMPLOYMENT
SUPPLEMENTARY
TALENT_INTRODUCTION
CONFIDENTIALITY
INTELLECTUAL_PROPERTY
PART_TIME
EXTERNAL_EXPERT
SERVICE
PROJECT
OTHER
```

每种 family 定义：

```text
max_active
overlap_policy
requires_employment_relationship
requires_assignment
affects_employment_end
affects_payroll
requires_signature
requires_approval
```

例：

```text
PRIMARY_EMPLOYMENT:
max_active_per_relationship = 1

SUPPLEMENTARY:
max_active = many

TALENT_INTRODUCTION:
max_active = school configurable
```

---

# 9. Agreement Type

```text
HrAgreementType
- id
- tenant_id
- code
- name
- family
- term_mode FIXED / OPEN_ENDED / EVENT_BOUND
- active
- requires_end_date
- requires_review_date
- signature_mode_policy
- numbering_rule_id
- rule_set_id
- workflow_policy_id
- overlap_policy
- version
```

示例：

```text
事业单位聘用合同
劳动合同
固定期限聘用合同
无固定期限合同
劳务协议
外聘教师协议
人才引进协议
补充协议
```

不把全国/某省具体合同类型硬编码为唯一选择。

---

# 10. HrAgreement

一个逻辑合同/协议身份。

```text
HrAgreement
- id UUID
- tenant_id
- agreement_no
- agreement_type_id
- agreement_family
- employment_relationship_id
- staff_master_id
- parent_agreement_id nullable
- root_agreement_id
- current_version_id nullable
- lifecycle_status
- contract_start_date
- contract_end_date nullable
- review_date nullable
- signed_date nullable
- effective_from nullable
- effective_to nullable
- governing_policy_version
- source
- version
- created_at
```

`agreement_no` 一旦正式签署：

```text
immutable
```

---

# 11. AgreementVersion

正式内容版本。

```text
HrAgreementVersion
- id
- tenant_id
- agreement_id
- version_no
- version_type
- template_version_id nullable
- source_event_id nullable
- status
- rendered_document_id nullable
- content_snapshot_json
- variable_snapshot_json
- terms_snapshot_json
- content_hash
- generated_at
- approved_at
- signed_at
- effective_from
- effective_to nullable
```

`version_type`：

```text
INITIAL
RENEWAL
AMENDMENT
CORRECTION
MIGRATION
```

---

# 12. 已签署版本不可变

一旦：

```text
SIGNED
```

禁止：

```text
UPDATE document body
UPDATE term snapshot
UPDATE content_hash
DELETE version
```

变化必须：

```text
new AgreementVersion
or AgreementEvent
```

---

# 13. AgreementTerm

重要条款结构化，不只存 PDF。

```text
HrAgreementTerm
- version_id
- term_code
- category
- value_type
- value_json
- display_text
- source
- sensitivity
```

V1 建议标准化：

```text
TERM_DURATION
POSITION_DUTY
WORK_LOCATION
WORKING_ARRANGEMENT
PROBATION
NOTICE_PERIOD
COMPENSATION_REFERENCE
BENEFIT_REFERENCE
CONFIDENTIALITY
IP
RENEWAL
TERMINATION
OTHER
```

注意：

> `COMPENSATION_REFERENCE` 可以表达约定标准或引用，但 HR15 才是工资计算权威。

---

# 14. Contract 日期语义

必须区分：

```text
created_at           系统创建时间
approved_at          审批通过时间
signed_at            双方签署完成时间
effective_from       法律/业务生效时间
contract_start_date  合同约定起始日
contract_end_date    合同约定终止日
review_date          续聘/评估开始日期
terminated_at        实际解除/终止时间
archived_at          归档时间
```

禁止用一个 start/end/status 代替全部语义。

---

# 15. 生命周期状态机

冻结：

```text
DRAFT
→ PREPARING
→ READY_FOR_APPROVAL
→ UNDER_APPROVAL
→ APPROVED
→ GENERATING_DOCUMENT
→ WAITING_SIGNATURE
→ PARTIALLY_SIGNED
→ SIGNED_WAITING_EFFECTIVE
→ ACTIVE
→ REVIEW_DUE
→ RENEWAL_IN_PROGRESS
→ EXPIRED
→ TERMINATED
→ ARCHIVED
```

异常/终局：

```text
RETURNED
REJECTED
SIGNATURE_FAILED
CANCELLED
VOID
```

---

# 16. 状态与日期不能互相“猜”

禁止：

```text
if end_date < today:
    status = EXPIRED
```

必须有正式 Lifecycle Service。

原因：

- 合同到期但有续签已签待生效；
- 合同解除早于原 end_date；
- 数据迁移可能存在历史；
- open-ended 无 end_date；
- end_date 到达后还要执行 employment termination/followup；
- 某些系统动作失败不能只靠日期静默改状态。

---

# 17. Contract Effective Job

后台：

```text
AgreementLifecycleScheduler
```

扫描：

```text
SIGNED_WAITING_EFFECTIVE due
ACTIVE review_date due
ACTIVE end_date approaching
ACTIVE end_date reached
signature expiry
renewal overdue
```

每项都是幂等领域动作。

---

# 18. HR07-01 合同台账施工卡

## 18.1 目标

做成真正的合同事实中心，而不是 Payroll 合同表。

路由：

```text
/hr/contracts
/hr/contracts/:agreementId
/hr/staff/:staffId/contracts
```

## 18.2 首页布局

```text
┌────────────────────────────────────────────────────────────┐
│ 合同台账                             [新建合同] [导入] [导出] │
│ 当前学校：XX职业技术学院   数据截至：21:30                  │
├────────────────────────────────────────────────────────────┤
│ 有效主合同 9865 │ 待签 31 │ 90日到期 126 │ 逾期未处理 8 │ 风险 17 │
├────────────────────────────────────────────────────────────┤
│ [全部][有效][待签署][待生效][续签中][已到期][已解除][异常]   │
├────────────────────────────────────────────────────────────┤
│ 合同号│人员│类型│组织│起始│到期│签署│当前版本│状态│风险       │
└────────────────────────────────────────────────────────────┘
```

KPI 可钻取。

## 18.3 筛选

```text
姓名/工号
合同号
Agreement Family
合同类型
组织
人员类别
用工性质
状态
签署状态
开始/结束日期
review date
是否存在补充协议
风险等级
```

## 18.4 合同详情

头部：

```text
YK-EMP-2026-000123
张三 · 专任教师
事业单位聘用合同
ACTIVE
2026-09-01 ~ 2031-08-31
Current Version V2
```

Tabs：

```text
合同摘要
正文与条款
版本
签署
审批
补充协议
事件
关联聘用关系
附件
风险
审计
```

## 18.5 主档右侧摘要

只显示轻量：

```text
当前有效版本
下次 review
剩余天数
签署状态
风险
```

复杂编辑始终独立页面。

## 18.6 Contract Timeline

```text
2026-08-20 创建
2026-08-23 审批
2026-08-25 学校签署
2026-08-26 员工签署
2026-09-01 生效
2031-06-01 Review Due
...
```

---

# 19. 台账权限

```text
hr07.agreement.view
hr07.agreement.view_terms
hr07.agreement.view_document
hr07.agreement.sensitive_view
hr07.agreement.export
```

学院 HR：

- 只看本学院 scope；
- 学校统一合同类型可以只读；
- 不自动具有下载所有签署文件权限。

---

# 20. Contract Document Security

签署合同属于 HIGH_SENSITIVE / LEGAL。

必须：

- private storage；
- signed short-lived URL；
- document hash；
- MIME；
- malware scan；
- watermark preview 可选；
- download audit；
- bulk download 异步；
- 禁止裸 `/media/contract.pdf`。

---

# 21. HR07-02 合同模板与规则施工卡

## 21.1 目标

把“合同长什么样”“哪些人用”“哪些字段必填”“是否可以续签”“到期提前多久 review”从代码中解耦。

路由：

```text
/hr/contracts/config/types
/hr/contracts/config/templates
/hr/contracts/config/templates/:id
/hr/contracts/config/rules
/hr/contracts/config/numbering
```

## 21.2 模板模型

```text
HrAgreementTemplate
- id
- tenant_id
- code
- name
- agreement_type_id
- status
- owner_org_id nullable

HrAgreementTemplateVersion
- template_id
- version_no
- effective_from
- effective_to
- content_source
- content_hash
- variable_schema_json
- clause_schema_json
- status DRAFT / ACTIVE / RETIRED
- approved_at
```

Case/Agreement 绑定具体 version。

---

# 22. 模板变量

例如：

```text
{{staff.name}}
{{staff.staff_no}}
{{employment.start_date}}
{{assignment.organization_name}}
{{assignment.position_name}}
{{agreement.start_date}}
{{agreement.end_date}}
{{terms.notice_period}}
```

变量必须来自 `AgreementVariableProvider Registry`。

禁止模板自由执行 Python/Jinja 任意表达式。

---

# 23. 模板变量安全

Provider：

```text
StaffProvider
EmploymentProvider
AssignmentProvider
AgreementProvider
PolicyProvider
```

每个 variable：

```text
code
data_type
sensitivity
source_domain
format
```

高敏字段默认不能进入普通模板。

---

# 24. 条款库

```text
HrAgreementClauseDefinition
- code
- name
- category
- body_template
- required
- conditional_rule
- version
```

支持：

- 固定条款；
- 条件条款；
- 可选条款；
- 学校级自定义条款。

---

# 25. Rule Set

```text
HrAgreementRuleSet
- id
- tenant_id
- code
- version
- applicable_staff_category
- applicable_employment_type
- applicable_post_category
- applicable_org_scope
- agreement_type
- rule_json
- status
```

规则示例：

```text
fixed_term → end_date required
review_date = end_date - 90 days
max_renewals = N
max_combined_duration = X
requires_probation_clause = ...
requires_talent_attachment = ...
```

具体 N/X 按学校制度配置，不写死。

---

# 26. Rule Engine 输出

```text
PASS
WARNING
BLOCKER
MANUAL_REVIEW
```

规则必须返回：

```text
rule_code
human_message
evidence
recommended_action
```

---

# 27. 合同编号规则

```text
HrAgreementNumberRule
- tenant_id
- prefix
- year_segment
- type_segment
- sequence_length
- reset_policy
- immutable_after_issue
```

分配采用 DB sequence / row lock。

禁止：

```text
max(no)+1
```

正式编号作废后不回收。

---

# 28. 模板发布治理

模板：

```text
DRAFT
→ UNDER_REVIEW
→ APPROVED
→ ACTIVE
→ RETIRED
```

ACTIVE 后禁止直接修改正文。

新版本：

```text
V3 → V4
```

历史 V3 合同继续绑定 V3。

---

# 29. HR07-03 签订与续签施工卡

## 29.1 业务目标

统一处理：

```text
新签
补签/历史补录
续签
固定期限延长
固定期限→无固定期限（按学校制度）
外聘/劳务协议签订
```

路由：

```text
/hr/contracts/signing
/hr/contracts/signing/new
/hr/contracts/signing/:caseId
/hr/contracts/renewals
/hr/contracts/renewals/:reviewId
```

---

# 30. Signing Case

```text
HrAgreementSigningCase
- id
- tenant_id
- employment_relationship_id
- agreement_type_id
- template_version_id
- proposed_start
- proposed_end
- review_date
- status
- source
- source_id
- agreement_id nullable
- approval_snapshot_id
- version
```

---

# 31. 新签向导 UI

```text
Step 1 选择人员/聘用关系
Step 2 选择合同类型
Step 3 系统匹配模板与规则
Step 4 填写合同期限和结构化条款
Step 5 规则校验
Step 6 预览合同
Step 7 审批
Step 8 签署
```

视觉：

```text
左：步骤
中：正式内容
右：规则/风险/来源事实
```

---

# 32. Preview

必须支持：

- HTML preview；
- PDF preview；
- 变量来源点击查看；
- 与模板默认值差异；
- rule warnings；
- 合同期限；
- Employment/Assignment 对账。

---

# 33. Approval

提交时冻结：

```text
ApprovalSnapshot
TemplateVersion
RuleSetVersion
VariableSnapshot
TermSnapshot
```

以后配置变化不影响此合同。

---

# 34. Contract Generation

状态：

```text
GENERATING
→ GENERATED
or GENERATION_FAILED
```

文档生成走异步 Job（复杂 PDF/批量签约）。

保存：

```text
content_hash
pdf_hash
template_version
render_engine_version
```

---

# 35. 签署模式

支持：

```text
OFFLINE
ELECTRONIC
HYBRID
```

OFFLINE：

- 下载；
- 线下签；
- 上传签署扫描件；
- 人工核验；
- 记录签署人/日期。

ELECTRONIC：

- 签署 envelope；
- 回调；
- reconciliation。

HYBRID：

- 一方电子签，一方线下等学校配置。

---

# 36. SignatureEnvelope

```text
HrSignatureEnvelope
- id
- tenant_id
- agreement_version_id
- provider
- provider_envelope_id
- status
- sent_at
- expires_at
- completed_at
- final_document_id
- final_document_hash
- last_callback_at
- reconciliation_status
- version
```

状态：

```text
DRAFT
SENT
VIEWED
PARTIALLY_SIGNED
COMPLETED
DECLINED
EXPIRED
FAILED
CANCELLED
```

---

# 37. Signature Participant

```text
HrSignatureParticipant
- envelope_id
- role SCHOOL / STAFF / WITNESS / OTHER
- signer_ref
- order_no
- status
- signed_at
- authentication_method
```

---

# 38. Webhook 安全

电子签：

- signature validation；
- replay protection；
- timestamp；
- provider event id unique；
- idempotency；
- unknown event quarantine；
- reconciliation job；
- callback 不直接信任“COMPLETED”而不拉取最终文件/校验 hash。

---

# 39. 签署完成 ≠ 立即生效

例如：

```text
2026-08-20 签完
2026-09-01 生效
```

必须：

```text
SIGNED_WAITING_EFFECTIVE
```

到生效日由 Lifecycle Service：

```text
ACTIVE
```

---

# 40. 续签 Review

不是 end_date 直接改长。

创建：

```text
HrAgreementRenewalReview
- agreement_id
- review_due_at
- decision_status
- reviewer
- performance_refs
- probation_ref nullable
- recommendation
- decision
- decided_at
- next_agreement_version_id
```

---

# 41. Renewal Decision

```text
PENDING
RENEW
RENEW_WITH_CHANGES
CONVERT_TYPE
DO_NOT_RENEW
TERMINATE
NEEDS_REVIEW
```

---

# 42. 续签业务链

```text
Review Due
→ 收集 HR12 考核/履职参考
→ 学院意见
→ HR review
→ 续聘决策
→ 新合同/新版本
→ 审批
→ 签署
→ 到期衔接
```

HR12 数据只能作为输入，不允许 HR07 修改 HR12 结果。

---

# 43. 续签日期连续性

默认规则可要求：

```text
new.start = old.end + policy-defined boundary
```

但不要在通用模型硬编码“+1天”。

采用统一 `[start, end)` 事实模型：

```text
旧：[2026-09-01, 2031-09-01)
新：[2031-09-01, 2036-09-01)
```

展示层可显示自然日期“至 2031-08-31”。

---

# 44. Future Contract

允许提前签署未来合同。

但检查：

```text
existing future version
overlap
gap
employment relationship validity
assignment future event
HR16 planned termination
```

冲突：

```text
REBASE_REQUIRED
HARD_OVERLAP
DEPENDENCY_CONFLICT
```

---

# 45. HR07-04 变更与解除施工卡

## 45.1 目标

明确区分：

```text
AMEND
CORRECT
SUSPEND
RESUME
TERMINATE
VOID
```

不能“编辑 active contract”。

---

# 46. AgreementEvent

```text
HrAgreementEvent
- id UUID
- tenant_id
- agreement_id
- event_type
- event_reason_id
- requested_effective_at
- approved_effective_at
- status
- initiator
- approval_snapshot
- before_snapshot
- after_snapshot
- version
```

---

# 47. Event Reason

```text
HrAgreementEventReason
- code
- event_type
- name
- requires_document
- requires_hr06_ref
- requires_hr16_ref
- default_workflow
- active
- version
```

---

# 48. 变更来源

可能来自：

```text
MANUAL_REQUEST
HR06_PERSONNEL_CHANGE
HR14_APPOINTMENT
POLICY_CHANGE
CORRECTION
```

例如 HR06 调岗：

```text
AssignmentChanged
→ ContractImpactEvaluator
→ NO_CHANGE / REVIEW_REQUIRED / AMENDMENT_REQUIRED
```

不自动直接改合同。

---

# 49. Amendment

补充/变更协议：

```text
parent_agreement_id
family = SUPPLEMENTARY
event_type = AMEND
```

可以产生新 Agreement 或同 Agreement 新 Version，由 AgreementType Policy 决定。

---

# 50. Change Diff UI

核心：

```text
原合同条款                变更后
────────────────────────────────
工作岗位：软件工程教师  → AI教师
工作地点：一校区        → 二校区
薪酬引用：原标准        → 待HR15复核
合同期限：不变
```

必须显示来源事件。

---

# 51. Suspension / Resume

某些合同/协议可有中止。

```text
ACTIVE
→ SUSPENDED
→ ACTIVE
```

中止必须：

- reason；
- start；
- expected resume；
- downstream impact。

是否允许由 AgreementType 规则决定。

---

# 52. Termination

合同解除/终止与人员离校高度相关，但权威边界：

```text
HR07：合同终止事实
HR16：离职/退休/离校总流程
```

HR16 可以发：

```text
EmploymentExitApproved
```

HR07：

```text
AgreementTerminationRequired
```

---

# 53. Termination 原因

```text
END_OF_TERM
MUTUAL_AGREEMENT
STAFF_RESIGNATION
SCHOOL_TERMINATION
RETIREMENT
DEATH
CONTRACT_BREACH
RELATIONSHIP_ENDED
OTHER
```

具体法律分类由学校/地区制度配置和法务审查，不把这套 enum 当法律结论全集。

---

# 54. Termination Status

```text
DRAFT
UNDER_APPROVAL
APPROVED_WAITING_EFFECTIVE
EFFECTIVE
CANCELLED
RESCINDED
```

future termination 支持。

---

# 55. Contract End 与 Employment End

重要：

> 合同到期 ≠ EmploymentRelationship 一定自动结束。

Policy：

```text
END_AGREEMENT_ONLY
REQUIRES_EMPLOYMENT_TERMINATION
CREATE_RENEWAL_DECISION
MANUAL_REVIEW
```

避免系统在合同到期日直接把员工“离职”。

---

# 56. Correction

Correction：

> 业务事实本来如此，系统录错。

不能用 Amendment 伪造业务变化。

```text
HrAgreementCorrection
- agreement_version_id
- corrected_fields
- reason
- evidence
- approved_by
- applied_at
- old_hash
- new_hash
```

已签署 PDF 不能被 correction 静默替换。

若签署文件本身错误：

- void 原签署版本；
- 重生成；
- 重新签署；
- 保留原件。

---

# 57. VOID

仅用于：

- 合同错误生成；
- 法律上未成立；
- 重复录入；
- 明确撤销的无效实例。

VOID 不 delete。

---

# 58. 已生效合同禁止删除

DB/API：

```text
DELETE /agreements/{id}
```

只允许 DRAFT 且无正式业务引用时使用。

正式合同：

```text
TERMINATE / VOID / ARCHIVE
```

---

# 59. HR07-05 聘期与到期预警施工卡

## 59.1 目标

不是“距离 end_date 30 天发邮件”。

这是合同风险和续聘决策控制中心。

路由：

```text
/hr/contracts/risks
/hr/contracts/reviews
/hr/contracts/calendar
```

---

# 60. 风险首页

```text
┌────────────────────────────────────────────────────────────┐
│ 聘期与到期预警                                             │
├────────────────────────────────────────────────────────────┤
│ 90日内到期 126 │ 30日内 48 │ 已过期未处理 8 │ 待签署 31 │ 高风险 12 │
├────────────────────────────────────────────────────────────┤
│ [到期][续聘评审][签署][资料][HR06影响][HR16离校冲突]       │
├────────────────────────────────────────────────────────────┤
│ 人员│合同│学院│到期日│Review│当前动作│Owner│风险│SLA       │
└────────────────────────────────────────────────────────────┘
```

---

# 61. Alert Policy

```text
HrAgreementAlertPolicy
- agreement_type_id
- review_offset_days
- warning_offsets_json
- escalation_offsets_json
- recipients
- action_required
- overdue_policy
- version
```

示例只是默认建议：

```text
180 天：可选早期提示
90 天：启动 review
60 天：学院意见
30 天：HR 高优先
7 天：升级
到期日：critical
过期未处理：daily/periodic escalation
```

学校可配置。

---

# 62. Risk 类型

```text
CONTRACT_EXPIRING
CONTRACT_EXPIRED_UNRESOLVED
REVIEW_NOT_STARTED
RENEWAL_NOT_SIGNED
SIGNATURE_EXPIRED
SIGNATURE_FAILED
DOCUMENT_MISSING
TEMPLATE_RETIRED
FUTURE_OVERLAP
EMPLOYMENT_MISMATCH
HR06_CHANGE_REVIEW_REQUIRED
HR16_EXIT_CONFLICT
AGREEMENT_WITHOUT_CURRENT_ASSIGNMENT
LEGACY_DRIFT
```

---

# 63. Risk Severity

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

必须由规则定义，不由前端随机配颜色。

---

# 64. Take Action

预警卡必须可以直接：

```text
开始续聘评审
发起续签
提醒签署
补充材料
检查 HR06 影响
发起解除
交给 HR16
```

不是只有“查看详情”。

---

# 65. 风险去重

同一合同：

```text
30天提醒
7天提醒
已到期
```

应更新同一 Risk Case 或关联为同一 incident family。

不能生成 20 条没人清的通知。

---

# 66. Risk Case

```text
HrAgreementRiskCase
- id
- tenant_id
- agreement_id
- risk_type
- severity
- opened_at
- due_at
- owner
- status
- resolved_at
- resolution
- version
```

状态：

```text
OPEN
ACKNOWLEDGED
IN_PROGRESS
RESOLVED
WAIVED
```

WAIVED 要权限+原因。

---

# 67. Data Scope

```text
SCHOOL
COLLEGE
ORGANIZATION
SELF
ASSIGNED_CASES
```

合同管理员一般 school scope。

学院 HR 可：

- 查看本学院；
- 发起 review；
- 提意见；
- 不一定能签署/终止。

---

# 68. 权限矩阵

```text
hr07.agreement.view
hr07.agreement.create
hr07.agreement.edit_draft
hr07.agreement.submit
hr07.agreement.approve
hr07.agreement.generate
hr07.agreement.issue
hr07.agreement.activate

hr07.renewal.review
hr07.renewal.decide

hr07.amend.create
hr07.termination.create
hr07.termination.approve
hr07.correction.create
hr07.void

hr07.template.view
hr07.template.manage
hr07.rule.manage

hr07.document.view
hr07.document.download
hr07.sensitive_download

hr07.risk.view
hr07.risk.manage
hr07.export
```

---

# 69. Separation of Duties

高风险动作可以配置 SoD：

```text
draft creator ≠ final approver
termination initiator ≠ final approver
correction requester ≠ approver
template editor ≠ template publisher
```

单人小团队模式可允许同一用户兼任，但必须：

- 显式 permission；
- 审计；
- 可在未来学校配置启用严格 SoD。

---

# 70. HR03 联动

HR03 提供：

```text
EmploymentRelationship
Assignment as-of
StaffMaster
```

HR07 查询：

```text
employment_relationship_id
assignment snapshot
```

合同不能复制当前组织作为长期权威。

如需展示签署时组织：

保存：

```text
signing_context_snapshot
```

---

# 71. HR05 联动

HR05 Activation：

```text
ContractSigningTaskRequested
```

是否 BLOCKS_ACTIVATION：

由学校 OnboardingPolicy 决定。

HR07 返回：

```text
NOT_REQUIRED
DRAFT
UNDER_APPROVAL
WAITING_SIGNATURE
SIGNED
ACTIVE
```

---

# 72. HR06 联动

HR06 生效：

```text
PersonnelChangeEffective
```

HR07 Impact Provider 输出：

```text
NO_IMPACT
REVIEW_REQUIRED
AMENDMENT_REQUIRED
NEW_AGREEMENT_REQUIRED
```

不能 HR06 自动改合同文本。

---

# 73. HR12 联动

续聘评审可读取：

```text
annual assessment
term assessment
ethics assessment
```

只读。

HR07 不重新计算考核。

---

# 74. HR14 联动

岗位聘任结果可能触发：

```text
AgreementReviewRequired
```

但 HR14 负责聘任事实，HR07 负责合同文件/条款。

---

# 75. HR15 联动

Horilla 当前把 `wage` 存 Contract 并回写 basic_salary。

终极版禁止 HR07 直接成为工资计算权威。

HR07：

```text
compensation_reference
agreed_compensation_term
```

HR15：

```text
actual salary structure
monthly payroll
allowances
deductions
```

若合同变更薪酬条款：

```text
CompensationAgreementChanged
→ HR15 review
```

---

# 76. HR16 联动

HR16 负责：

```text
离职
调出
退休
离校交接
```

HR07 负责：

```text
终止/解除合同
```

HR16 Completion Gate 可要求：

```text
all required agreements ended/terminated
```

---

# 77. HR08 联动

外聘/兼职教师：

HR08 负责身份和聘用业务对象。

HR07 可提供：

```text
PART_TIME
EXTERNAL_EXPERT
SERVICE
```

协议生命周期。

---

# 78. 文件模型

```text
HrAgreementDocument
- id
- agreement_id
- agreement_version_id
- document_type
- file_id
- hash
- source
- signature_status
- sensitivity
- uploaded_by
- uploaded_at
```

类型：

```text
DRAFT
GENERATED_UNSIGNED
SIGNED_FINAL
SUPPLEMENTARY
APPROVAL_EVIDENCE
TERMINATION_EVIDENCE
OTHER
```

---

# 79. Document Finality

`SIGNED_FINAL`：

- immutable；
- hash；
- legal hold；
- retention；
- download audit。

如果电子签平台重新返回相同 envelope 不同 bytes：

```text
INTEGRITY_CONFLICT
```

进入人工调查。

---

# 80. Audit

正式：

```text
HrAgreementAuditEvent
SensitiveAgreementAccessLog
```

审计：

- 查看敏感合同；
- 下载；
- 创建；
- 编辑 draft；
- 模板发布；
- 规则变化；
- 提交；
- approve/reject/return；
- 文档生成；
- 电子签发送；
- webhook；
- activation；
- renewal；
- amendment；
- termination；
- correction；
- void；
- export；
- Legacy drift repair。

---

# 81. API 总合同

基路径：

```text
/api/hr/v1/contracts/*
```

响应根：

```json
{
  "apiVersion": "v1",
  "schemaVersion": "hr07.1",
  "requestId": "uuid",
  "data": {}
}
```

V1：

- additive-only；
- 不删字段；
- 不改类型；
- enum 新值前端 fallback；
- breaking `/v2/`。

---

# 82. 核心 API：台账

```http
GET /api/hr/v1/contracts
GET /api/hr/v1/contracts/{id}
GET /api/hr/v1/contracts/{id}/versions
GET /api/hr/v1/contracts/{id}/timeline
GET /api/hr/v1/contracts/{id}/documents
GET /api/hr/v1/staff/{staffId}/contracts
```

---

# 83. 核心 API：模板与规则

```http
GET    /api/hr/v1/contracts/types
POST   /api/hr/v1/contracts/types

GET    /api/hr/v1/contracts/templates
POST   /api/hr/v1/contracts/templates
POST   /api/hr/v1/contracts/templates/{id}/versions
POST   /api/hr/v1/contracts/template-versions/{id}/submit
POST   /api/hr/v1/contracts/template-versions/{id}/publish

GET    /api/hr/v1/contracts/rules
POST   /api/hr/v1/contracts/rules
POST   /api/hr/v1/contracts/rules/evaluate
```

---

# 84. 核心 API：签订续签

```http
POST /api/hr/v1/contracts/signing-cases
GET  /api/hr/v1/contracts/signing-cases/{id}
POST /api/hr/v1/contracts/signing-cases/{id}/preview
POST /api/hr/v1/contracts/signing-cases/{id}/submit
POST /api/hr/v1/contracts/signing-cases/{id}/approve
POST /api/hr/v1/contracts/signing-cases/{id}/generate
POST /api/hr/v1/contracts/signing-cases/{id}/send-signature

POST /api/hr/v1/contracts/{id}/renewal-reviews
POST /api/hr/v1/contracts/renewal-reviews/{id}/decide
```

---

# 85. 核心 API：变更解除

```http
POST /api/hr/v1/contracts/{id}/events
POST /api/hr/v1/contracts/events/{id}/preview
POST /api/hr/v1/contracts/events/{id}/submit
POST /api/hr/v1/contracts/events/{id}/approve
POST /api/hr/v1/contracts/events/{id}/apply

POST /api/hr/v1/contracts/{id}/corrections
POST /api/hr/v1/contracts/{id}/void
```

---

# 86. 核心 API：风险

```http
GET  /api/hr/v1/contracts/risks
GET  /api/hr/v1/contracts/reviews
POST /api/hr/v1/contracts/risks/{id}/acknowledge
POST /api/hr/v1/contracts/risks/{id}/resolve
POST /api/hr/v1/contracts/risks/{id}/waive
```

---

# 87. 写操作合同

必须：

```text
Idempotency-Key
If-Match / version
```

关键冲突：

```text
409 AGREEMENT_VERSION_CONFLICT
409 AGREEMENT_OVERLAP
409 FUTURE_AGREEMENT_CONFLICT
409 SIGNATURE_ALREADY_COMPLETED
409 AGREEMENT_ALREADY_ACTIVE
409 AGREEMENT_PENDING_APPROVAL
409 RENEWAL_ALREADY_EXISTS
409 TERMINATION_DEPENDENCY_CONFLICT
```

---

# 88. 错误码

```text
AGREEMENT_TYPE_INVALID
AGREEMENT_RULE_BLOCKED
AGREEMENT_TEMPLATE_VERSION_INVALID
AGREEMENT_NUMBER_CONFLICT
AGREEMENT_OVERLAP
AGREEMENT_EMPLOYMENT_MISMATCH
AGREEMENT_ASSIGNMENT_MISMATCH
AGREEMENT_SIGNING_CONTEXT_STALE
AGREEMENT_FUTURE_RECORD_CONFLICT
AGREEMENT_ALREADY_SIGNED
AGREEMENT_DOCUMENT_INTEGRITY_ERROR
SIGNATURE_PROVIDER_ERROR
SIGNATURE_CALLBACK_INVALID
RENEWAL_NOT_ALLOWED
RENEWAL_REVIEW_REQUIRED
TERMINATION_NOT_ALLOWED
CORRECTION_REQUIRES_APPROVAL
VERSION_CONFLICT
```

---

# 89. Future Record 冲突

例如：

```text
当前合同到 2027-08-31
已经提前签了 2027-09-01 新合同
现在用户又要把当前合同续到 2028
```

必须：

```text
FUTURE_AGREEMENT_CONFLICT
```

不能覆盖未来合同。

---

# 90. Data Freshness

HR07 Dashboard / HR01：

```text
sourceUpdatedAt
calculatedAt
maxStaleSeconds
hardExpireSeconds
status
```

但：

- overlap check；
- rule evaluation；
- signing；
- activation；
- termination；

必须读强一致新数据，不用陈旧缓存。

---

# 91. Outbox Events

```text
AgreementDraftCreated
AgreementApproved
AgreementGenerated
AgreementSignatureRequested
AgreementSigned
AgreementActivated
AgreementReviewDue
AgreementRenewalStarted
AgreementRenewed
AgreementAmended
AgreementTerminated
AgreementVoided
AgreementCorrectionApplied
AgreementRiskOpened
AgreementRiskResolved
```

---

# 92. 电子签 Provider Adapter

```text
SignatureProvider
- create_envelope()
- send()
- get_status()
- download_final_document()
- cancel()
- verify_webhook()
```

V1 没接真实厂商时：

- 允许 `OFFLINE` 模式生产使用；
- 不允许伪造电子签成功；
- Mock 仅测试环境。

---

# 93. 异步任务

必须走 Job：

- 大批合同生成；
- 批量签署包；
- 大批导出；
- 文件打包；
- 大规模到期扫描；
- 签署 provider reconciliation；
- Legacy migration。

状态：

```text
PENDING
RUNNING
SUCCESS
FAILED
```

---

# 94. Excel

支持：

- 历史合同导入；
- 台账导出；
- 批量创建续聘 review；
- 历史合同状态迁移；
- 合同风险清单。

流程：

```text
template
→ upload
→ staging
→ validate
→ error workbook
→ confirm
→ async
→ result
→ audit
```

禁止 Excel 直接 SQL UPDATE Contract。

---

# 95. 历史合同迁移

Legacy Contract → HR07 迁移时：

分类：

```text
CLEAR
AMBIGUOUS
INVALID
```

问题示例：

- active 多份；
- start/end 重叠；
- status 和日期矛盾；
- contract_document 缺失；
- wage 与 payroll 当前不一致；
- Employee 已离职但 contract active。

AMBIGUOUS 不自动“猜”。

---

# 96. Legacy Contract Mapping

S0 必须生成：

```text
docs/hr07/LegacyContractMapping.md
```

最低映射：

| Horilla Contract | HR07 | 策略 |
|---|---|---|
| employee_id | HR03 employment/staff ref | 重映射 |
| contract_name | Agreement title/type | ADAPT |
| start/end | Agreement dates | migrate |
| contract_status | Lifecycle status | map with validation |
| wage | HR15 / term reference | 移出权威 |
| pay_frequency | HR15 | 移出 |
| filing_status | HR15/tax | 移出 |
| department | signing snapshot only | 不作权威 |
| job_position | signing snapshot only | 不作权威 |
| job_role | signing snapshot only | 不作权威 |
| shift/work_type | HR11/current assignment | 移出 |
| notice_period | AgreementTerm | migrate |
| document | AgreementDocument | migrate |
| leave deduction fields | HR11/HR15 | 移出 |
| history | migration evidence | 非正式 ledger |

---

# 97. Legacy 退出合同

```text
LEGACY_CONTRACT_ONLY
→ DUAL_READ_COMPARE
→ HR07_AUTHORITY
```

## LEGACY_CONTRACT_ONLY

Payroll Contract 仍权威。

## DUAL_READ_COMPARE

新 HR07 读写影子 + Legacy projection，对账：

```text
employee
contract dates
status
document
wage reference
```

## HR07_AUTHORITY

- 新合同只写 HR07；
- Legacy Contract 只 projection；
- 旧 Contract create/edit 页面跳 HR07；
- 不自动 fallback；
- Payroll 从 HR15/HR07 provider 取明确字段。

---

# 98. Legacy Projection

仅为旧模块兼容：

```text
current PRIMARY_EMPLOYMENT Agreement
        ↓
Horilla Contract
```

projection 不包括所有 supplementary agreements。

Payroll 旧代码需要的 wage：

不得从 HR07 签署文件临时解析。

由 HR15 明确提供。

---

# 99. UI 公共组件

继承 HR01–HR06。

新增：

```text
HrAgreementHeader
HrAgreementStatusBadge
HrAgreementFamilyBadge
HrAgreementRiskBadge
HrAgreementTimeline
HrAgreementTermTable
HrAgreementVersionRail
HrContractDateRange
HrContractReviewBadge
HrSignatureStatus
HrSignatureParticipants
HrContractDocumentPreview
HrAgreementDiff
HrRuleEvaluationPanel
HrTemplateVersionBadge
HrContractPreview
HrRenewalDecisionBar
HrAgreementEventTimeline
HrContractRiskCard
HrExpiryCalendar
HrAgreementRelationshipMap
```

---

# 100. 顶级 UI：合同台账

不是普通 Excel 表复制。

首屏：

- KPI；
- 风险；
- 到期趋势；
- 待行动；
- 合同列表。

但“正式合同事实”仍以表格为核心。

---

# 101. 顶级 UI：合同详情

建议：

```text
┌──────────────────────────────────────────────────────────┐
│ 合同号 / 类型 / 人员 / 状态 / 当前版本                    │
│ 2026-09-01 ━━━━━━━━━━━━━━━ 2031-08-31                    │
├──────────────────────────────────────────────────────────┤
│ 关键条款                │ 当前风险                         │
│ 聘期 5年                │ 90天后进入续聘评审                │
│ 岗位 软件工程教师       │                                  │
│ Notice 30天             │                                  │
├──────────────────────────────────────────────────────────┤
│ Tabs: 正文 条款 版本 签署 审批 事件 文件 风险 审计         │
└──────────────────────────────────────────────────────────┘
```

---

# 102. 顶级 UI：签订向导

不要巨大长表单。

采用：

```text
关系事实
→ 合同类型
→ 模板
→ 条款
→ Preview
→ Approval
→ Signature
```

每步右侧显示：

```text
规则
阻断
来源数据
```

---

# 103. 顶级 UI：续聘中心

不是“修改 End Date”。

左：

```text
待 Review
到期风险
```

中：

```text
当前合同事实
履职参考
HR12考核
```

右：

```text
RENEW
RENEW_WITH_CHANGES
CONVERT
DO_NOT_RENEW
```

---

# 104. Mobile

移动端重点支持：

- 本人查看合同摘要；
- 下载本人签署件；
- 签署跳转；
- manager approval；
- renewal意见；
- 风险确认。

复杂模板配置和合同生成 PC 优先。

---

# 105. Accessibility

- 状态不只颜色；
- timeline 有文本；
- PDF 有下载替代；
- 签署状态 screen reader；
- approval 键盘；
- form errors；
- focus；
- mobile；
- diff old/new 有明确 label。

---

# 106. Visual Regression

截图：

```text
合同台账
合同详情
模板中心
模板编辑/预览
规则评估
签订向导
合同 Preview
待签署
续聘中心
变更 diff
终止
风险中心
到期日历
empty/error/stale/permission
```

视口：

```text
1440
1280
768
375
```

---

# 107. 后端目录建议

```text
hr_contracts/
    models/
        agreement.py
        agreement_type.py
        agreement_version.py
        agreement_term.py
        template.py
        rule.py
        signing.py
        event.py
        renewal.py
        risk.py
        document.py
        audit.py

    services/
        agreement_service.py
        rule_service.py
        template_service.py
        signing_service.py
        generation_service.py
        renewal_service.py
        amendment_service.py
        termination_service.py
        lifecycle_service.py
        correction_service.py
        risk_service.py

    selectors/
    policies/
    api/
    integrations/
        hr03.py
        hr05.py
        hr06.py
        hr08.py
        hr12.py
        hr14.py
        hr15.py
        hr16.py
        signature_provider.py

    projections/
        horilla_contract.py

    jobs/
    tests/
```

---

# 108. 不建议继续留在 payroll 的原因

Contract 是跨：

```text
employment
legal docs
approval
signature
renewal
termination
```

的核心 HR 域。

Payroll 只是其一个消费者。

因此新 authority：

```text
hr_contracts
```

而不是继续：

```text
payroll.Contract += 50 fields
```

---

# 109. DB Constraints

至少：

- agreement_no tenant unique；
- type/family compatible；
- version_no agreement unique；
- version >= 1；
- signed version hash non-null；
- FINAL document hash non-null；
- one current version pointer valid；
- event type/reason compatible；
- future overlap policy；
- tenant FKs consistent；
- signature provider event id unique；
- renewal review unique per review cycle；
- risk dedupe key unique while OPEN。

---

# 110. 索引

```text
(tenant_id, lifecycle_status)
(tenant_id, staff_master_id, lifecycle_status)
(tenant_id, employment_relationship_id)
(tenant_id, contract_end_date)
(tenant_id, review_date)
(tenant_id, agreement_type_id, lifecycle_status)
(agreement_id, version_no)
(agreement_id, effective_from)
(risk_type, severity, status)
```

---

# 111. 列表查询规范

```text
WHERE
→ COUNT
→ ORDER
→ PAGE
```

禁止 Python 后过滤。

大台账考虑 cursor pagination。

---

# 112. 数据质量规则

至少：

```text
ACTIVE 无 signed version
ACTIVE 无 employment relationship
fixed-term 无 end date
open-ended 却有非法规则
current_version 指向非正式版本
SIGNED document hash 缺失
Agreement 与 HR03 employment 日期不一致
Expired 无 renewal/termination decision
Renewed 出现日期 overlap/gap
HR16 已离校但主合同 active
Signature completed 但 final document 缺失
Legacy projection drift
```

---

# 113. 可观测性

Metrics：

```text
hr07_active_agreements
hr07_agreements_expiring
hr07_expired_unresolved
hr07_signature_failed_total
hr07_generation_failed_total
hr07_renewal_overdue_total
hr07_future_conflict_total
hr07_legacy_drift_total
hr07_risk_open_total
```

---

# 114. 日志

记录：

```text
requestId
tenant
agreement_id
staff_master_id
action
status
duration
error_code
```

禁止合同正文、身份证、薪资明文进入日志。

---

# 115. 安全测试矩阵

必须：

- A校看不到B校；
- 学院A不能看B学院合同；
- 本人只看本人；
- manager 按 scope；
- contract document IDOR；
- signed URL expiry；
- sensitive download audit；
- template manage；
- termination permission；
- correction/void permission；
- signature webhook spoof；
- replay；
- export scope；
- background job tenant；
- malformed PDF/office file；
- XSS；
- CSRF；
- rate limit。

---

# 116. 事务与并发测试

必须：

1. 两个管理员同时创建主合同；
2. 两个续签 review 同时生成；
3. contract number sequence 并发；
4. 签署 webhook 重复；
5. signature callback 与 cancel 同时；
6. lifecycle scheduler 与人工 activate 同时；
7. HR16 termination 与 renewal 同时；
8. HR06 amendment-required 与 renewal 同时；
9. future contract overlap；
10. correction 与 new version 同时。

---

# 117. HR07-01 验收

- 台账；
- 多协议；
- current version；
- history；
- document；
- scope；
- export；
- as-of；
- risk；
- audit。

---

# 118. HR07-02 验收

- type；
- family；
- template；
- template version；
- variable provider；
- clause；
- rule；
- numbering；
- publish/retire；
- 历史合同不受模板更新影响。

---

# 119. HR07-03 验收

- new signing；
- approval；
- preview；
- generation；
- offline signature；
- electronic adapter contract；
- signed waiting effective；
- activation；
- renewal review；
- renew with changes；
- convert type；
- future contract；
- idempotency。

---

# 120. HR07-04 验收

- amendment；
- HR06 impact；
- suspend/resume；
- termination；
- HR16 linkage；
- correction；
- void；
- future event；
- history；
- immutable signed version。

---

# 121. HR07-05 验收

- review date；
- multi-offset alerts；
- Take Action；
- overdue escalation；
- risk dedupe；
- signature risk；
- HR06/HR16 conflict；
- calendar；
- owner/SLA；
- resolved/waived audit。

---

# 122. E2E 主链

必须：

1. HR05 正式入职；
2. 建 signing case；
3. 匹配合同规则；
4. 生成 preview；
5. 审批；
6. 生成文件；
7. 签署；
8. future effective；
9. ACTIVE；
10. 到期进入 review；
11. HR12参考；
12. 决定续签；
13. 新版本签署；
14. 连续生效；
15. 历史版本仍可查。

---

# 123. E2E 异常链

必须：

- 签署拒绝；
- webhook 重复；
- 文档 hash 冲突；
- future overlap；
- template retired；
- HR06 岗位变化要求 amendment；
- HR16 离校与续签冲突；
- expired unresolved；
- correction；
- void；
- Legacy discrepancy。

---

# 124. Performance

建议：

- Contract list p95 < 600ms；
- detail p95 < 700ms；
- rule evaluation p95 < 500ms；
- preview API p95 < 1s（不含 PDF）；
- risk dashboard p95 < 800ms；
- 10万合同台账可分页；
- 大 PDF generation async；
- bulk export async；
- dashboard 禁止 N+1。

---

# 125. Legacy 数据迁移门

切换前必须得到：

```text
LegacyContractMigrationReport
```

包含：

```text
total
migrated
ambiguous
blocked
missing_documents
overlap
status_conflict
employee_mapping_conflict
payroll_dependency
```

所有 P0 conflict 必须人工处理或有批准的 migration policy。

---

# 126. Payroll 解耦门

HR07 Authority 前必须确认：

```text
哪些 payroll calculations 仍直接读取 Contract.wage
哪些 leave calculations 读取 contract flags
哪些 scheduler 修改 contract_status
哪些 EmployeeWorkInformation.basic_salary 由 Contract save 回写
```

逐个迁移到：

```text
HR15 compensation provider
HR11 leave policy
HR07 lifecycle provider
```

否则不能切 authority。

---

# 127. Legacy 页面接管

authority 后：

旧：

```text
/payroll/contracts/*
```

处理：

```text
list → redirect/compat to HR07
create → redirect HR07
edit active → 禁止
detail → compatibility view
```

不要长期留两个可编辑入口。

---

# 128. API Contract Tests

验证：

- apiVersion；
- schemaVersion；
- requestId；
- error envelope；
- pagination；
- filtering；
- If-Match；
- Idempotency-Key；
- enum fallback；
- additive compatibility；
- document permission。

---

# 129. Data Freshness / STALE

Dashboard metric 定义：

```text
maxStaleSeconds
hardExpireSeconds
```

`MetricCard`：

```text
OK
STALE
PARTIAL
ERROR
UNAVAILABLE
```

但合同具体状态和签署详情不得拿过期指标卡缓存代替。

---

# 130. 缓存

可以缓存：

- type/template catalog；
- dashboard aggregate；
- risk counts。

cache key 必须含：

```text
tenant
scope
permission profile/version
config version
```

合同正文/敏感 document URL 不做共享缓存。

---

# 131. 数据保留

```text
HrAgreementRetentionPolicy
```

正式 signed contract 通常长期/依法保留。

系统需要：

- legal hold；
- archive；
- retention policy；
- no hard delete；
- 员工离校后仍保留合法档案。

具体保存年限按学校/法律制度配置，不写死。

---

# 132. Search

普通：

```text
agreement no
staff name
staff no
type
organization
```

不把全文合同正文默认放入普通搜索索引。

如未来做全文检索：

- 独立权限；
- tenant isolation；
- sensitive index；
- access audit。

---

# 133. AI 使用红线

AI 可：

- 合同条款差异摘要；
- 缺字段提醒；
- 风险聚合；
- 模板变量检查；
- 续签资料摘要。

AI 不可：

- 自动作法律结论；
- 自动决定解除合同；
- 自动判断条款是否合法；
- 不经人审修改正式合同；
- 把生成内容直接变成签署终稿。

所有 AI 内容：

```text
advisory / draft
human review required
```

---

# 134. 参考外部官方依据

## Workday

官方主题：Setup Considerations: Employee Contracts  
重点：fixed/open-ended contract、contract review、renew/end、rule、max renewal/duration、business process integration、security。

## SAP SuccessFactors Employee Central

官方主题：
- End of Contract Alert
- Initiate Contract Extension
- Business Rules in Employee Central
- Types of Employment

重点：contract end alerts、workflow、event reason、fixed-term rules、Take Action。

## Oracle Fusion Cloud HCM

官方主题：
- How You Manage Contracts
- Date Effectivity
- Contract Extension / Employment Contracts

重点：Contract 与 Assignment/Work Relationship 关联、extension history、effective-dated update 与 correction、future record 限制。

## 高校制度校正

参考教育行政/高校岗位设置聘用制度公开文件：
- 高校应区别人员类型采用不同聘用合同；
- 合同应明确岗位职责、条件、待遇、期限及变更/解除/终止；
- 岗位调整时合同相关内容需要相应变更；
- 合同期满前需及时开展续聘/岗位调整/解聘决策。

施工时 S0 必须按目标学校所在地和学校自身制度重新核验具体规则。

---

# 135. AI 施工顺序

收到整份总册后，AI 必须先 S0，不允许直接大改。

## HR07-S0 基线复审

逐目录审计：

```text
payroll/models/models.py
payroll/forms/*
payroll/cbv/*
payroll/views/*
payroll/urls/*
payroll/scheduler.py
employee/*
horilla_documents/*
horilla_audit/*
notifications/*
HR03 authority
HR05 integration
HR06 integration
HR15 planned boundary
```

输出：

```text
HR07_GAP_MATRIX.md
LegacyContractMapping.md
PayrollContractDependencyMap.md
AgreementTypeMatrix.md
HR07_TASK_TREE.md
HR07_RISK_REGISTER.md
```

必须列出：

```text
所有直接创建/编辑 Contract 的入口
所有读取 Contract.wage 的入口
所有 Contract save 副作用
所有到期 scheduler
所有 payroll/leave 对 Contract 的依赖
```

S0 禁止大改业务。

---

# 136. HR07-S1

基础契约：

- enums；
- permissions；
- API envelope；
- AgreementFamily/Type；
- event/reason；
- 公共 UI components。

---

# 137. HR07-S2

Authority Models：

```text
Agreement
AgreementVersion
AgreementTerm
AgreementDocument
Template/Version
RuleSet
NumberRule
```

+ migrations + constraints。

---

# 138. HR07-S3

HR07-01 合同台账：

- list；
- detail；
- version timeline；
- documents；
- scope；
- audit。

---

# 139. HR07-S4

HR07-02 模板与规则：

- template version；
- variables；
- clauses；
- rules；
- number sequence；
- config UI。

---

# 140. HR07-S5

HR07-03 签订：

- signing case；
- preview；
- approval；
- generation；
- offline signature；
- signature adapter；
- activation。

---

# 141. HR07-S6

HR07-03 续签：

- review；
- renewal decision；
- new version/agreement；
- date continuity；
- future conflict。

---

# 142. HR07-S7

HR07-04：

- amendment；
- termination；
- suspend/resume；
- correction；
- void；
- HR06/HR16 linkage。

---

# 143. HR07-S8

HR07-05：

- lifecycle scheduler；
- risk engine；
- alert policy；
- Take Action；
- escalation；
- calendar。

---

# 144. HR07-S9

Legacy Projection + Payroll decoupling：

- HR15 provider；
- HR11 provider；
- old Contract projection；
- old edit endpoint blocking。

---

# 145. HR07-S10

Legacy Migration + DUAL_READ_COMPARE。

---

# 146. HR07-S11

生产级验收：

```text
security
concurrency
performance
API contracts
E2E
accessibility
visual regression
migration/rollback
signature reconciliation
```

---

# 147. HR07-S12

Authority 切换演练：

```text
LEGACY_CONTRACT_ONLY
→ DUAL_READ_COMPARE
→ HR07_AUTHORITY
```

---

# 148. HR07-S13 最终封板

只有全部通过：

```text
HR07 READY FOR ACCEPTANCE
```

---

# 149. AI 禁止越界

AI 不得：

- 在 HR07 再建 EmploymentRelationship；
- 把 HR15 Payroll 做进合同；
- 把 HR11 Leave policy 写进 Agreement；
- 把 HR16 离校流程整体搬进 HR07；
- 修改已签署版本；
- 直接修改 active contract 正文；
- 续签只改 end_date；
- 把 correction 当 amendment；
- delete 正式合同；
- 用 mock 电子签冒充成功；
- 为 UI 好看制造 fake contract；
- 放宽 tenant；
- 关闭 403 解决权限；
- 同步批量 PDF；
- 让 Excel 绕过 service；
- 自动 fallback legacy；
- 合并 main；
- 跳过 migration/test。

---

# 150. 最终封板条件

## 业务

- 5 个三级模块闭环；
- 多协议/主合同语义正确；
- 新签、续签、变更、解除、终止、纠错可区分；
- 签署、生效、到期、review 日期语义正确；
- HR03/05/06/12/14/15/16 联动边界正确；
- expired unresolved 有正式风险闭环。

## 数据

- signed version immutable；
- template/rule/version frozen；
- content/document hash；
- future conflict；
- renewal history；
- effective-dated history；
- Legacy mapping 完整；
- Payroll Contract 副作用全部解耦或有兼容计划。

## 安全

- tenant；
- data scope；
- document；
- sensitive download；
- electronic signature webhook；
- audit；
- SoD；
- exports。

## 技术

- DB constraints；
- idempotency；
- optimistic locking；
- background jobs；
- outbox；
- reconciliation；
- API version；
- observability；
- migration rollback。

## 前端

- 台账；
- 模板规则；
- 签订续签；
- 变更解除；
- 风险中心；
- mobile 查看/审批；
- 375/768/1280/1440；
- accessibility；
- visual regression；
- empty/error/stale/permission。

全部满足才允许：

```text
HR07 READY FOR ACCEPTANCE
```

否则：

```text
HR07 NOT READY
blocking:
- ...
```

---

# 151. 最终架构冻结图

```text
                  HR03
        EmploymentRelationship
                    │
                    ▼
              HR07 Agreement
                    │
      ┌─────────────┼─────────────┐
      │             │             │
 AgreementType   Template       RuleSet
      │             │             │
      └─────────────┼─────────────┘
                    ▼
             AgreementVersion
                    │
          Approval / Generation
                    │
                    ▼
             SignatureEnvelope
                    │
                    ▼
          SIGNED_WAITING_EFFECTIVE
                    │
                    ▼
                  ACTIVE
                    │
      ┌─────────────┼───────────────┐
      │             │               │
   Renewal       Amendment       Termination
      │             │               │
      └─────────────┼───────────────┘
                    ▼
             Immutable History
                    │
                    ▼
                 Risk Engine
```

跨域：

```text
HR05 ── Contract task ───────────────→ HR07
HR06 ── PersonnelChangeEffective ───→ Contract Impact
HR12 ── Assessment results ─────────→ Renewal Review
HR14 ── Appointment result ─────────→ Contract Impact
HR15 ← Compensation reference ────── HR07
HR16 ── Exit/Retirement ────────────→ Agreement Termination
```

Legacy：

```text
HR07 Authority
      ↓
Legacy Contract Projection
      ↓
Old Payroll Compatibility
```

---

# 152. 编码 AI 首条执行指令

```text
读取《07_HR07_合同与聘用_施工总册_终极版.md》。

先不要修改业务代码。

执行 HR07-S0：

1. 逐目录审计 payroll Contract、forms、views/cbv、scheduler、employee、documents、audit、notifications；
2. 列出当前 Contract 的全部字段、状态、保存副作用、到期逻辑、Payroll/Leave依赖；
3. 读取 HR03 已落地 EmploymentRelationship/Assignment 事实层，不得在 HR07 建第二套；
4. 读取 HR05/HR06 既有服务合同，建立跨域接口矩阵；
5. 输出 HR07_GAP_MATRIX.md；
6. 输出 LegacyContractMapping.md；
7. 输出 PayrollContractDependencyMap.md；
8. 输出 AgreementTypeMatrix.md；
9. 输出 HR07_TASK_TREE.md 与 HR07_RISK_REGISTER.md；
10. 对每个旧 Contract 入口标记 KEEP / ADAPT / REDIRECT_TO_HR07 / READONLY / REMOVE_LATER；
11. 标记 P0：合同覆盖历史、Payroll副作用、多合同语义、日期/effective冲突、电子签安全、权限、Legacy迁移；
12. 不合并 main、不删除 legacy、不降低权限、不用 mock 冒充生产完成。

S0 复审通过后，再严格按 S1 → S13 顺序施工。
每阶段必须跑对应测试并报告真实通过/失败数量。
```

---

**文档状态：V1.0 终极冻结版。**
