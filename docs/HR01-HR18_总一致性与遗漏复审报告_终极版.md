# HR01–HR18 总一致性与遗漏复审报告（终极版）

> 产品：跃科高校人事管理与教师发展系统  
> 审计对象：HR01–HR18 共 18 份《施工总册_终极版》  
> 参照最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`
> 审计日期：2026-08-09  
> 文档性质：**不是 HR19，不新增产品二级模块；本文件是 18 册的总一致性复审、遗漏补丁清单和统一施工闸门。**  
> 使用方式：编码 AI 在正式施工 HR01–HR18 之前，先按本文件完成 P0 合同修订，再将 P1 业务空洞补回指定总册。

# 0. 最终判断

18 册的**主体业务链已经完整**：组织岗位 → 主档 → 招聘 → 入职 → 异动 → 合同 → 外聘 → 资格/双师 → 培训企业实践 → 考勤请假 → 年度/聘期考核 → 职称 → 岗位聘任 → 薪酬 → 退休离校 → 教职工服务 → 人事数据中心。

这次复审没有发现需要推翻 18 模块结构的理由，也**不建议新增 HR19**。

但当前 18 册还不能视为“拿给编码 AI 后完全不会打架”。复审确认两类问题：
- **7 个 P0 全局合同冲突**：00 继承、API 根路径、数据库目标、HR04/HR05 接管策略、事件命名、Permission namespace、HR01/HR18 Metric Authority。
- **3 个 P1 真业务空洞**：事业单位正式奖励/处分/复核申诉与人事争议、干部/教职工人事档案管理边界、职业年金与福利计划。
- **2 个 P1 施工一致性问题**：早期总册 S0–S9/S11/S12 与后期 S0–S13 不统一；HR16 缺少明确的前置标准继承头。
- **若干 P2 扩展项**：准聘长聘、博士后、因私出访、干部任免/专门干部管理、外籍人员许可等。对当前高职/职业院校主战场不作为封板阻断。

因此最终建议不是“再写更多模块”，而是：

```text
00 全局合同修订
→ 18 册统一合同补丁
→ 3 个业务空洞补回现有模块
→ 18 册 Cross-Document Gate
→ 才进入逐模块编码施工
```

# 1. 审计范围与方法

- 逐份读取 HR01–HR18 终极版全文，而不是只看标题。
- 抽取 API 路径、数据库假设、Authority、Provider、Event、Permission、Metric、Legacy/Cutover、S0–S13、Final Gate。
- 对 HR01↔HR18、HR03↔HR13、HR03↔HR14↔HR15 等高风险跨域做双向对撞。
- 以 00 全局架构合同作为后置统一裁决基线。
- 额外交叉核验当前项目规则：项目现有 `CLAUDE.md` 已明确 MySQL-only；因此旧册 PostgreSQL 专属设计属于必须处理的真实冲突。
- 外部校正只用于判断是否存在真正业务空洞，不用外部知识改写 18 册已经冻结的业务事实。

本报告把结果分为：
- **P0**：不修就可能形成双主、API 分裂、数据库无法落地、权限/事件不兼容，必须在正式编码前处理。
- **P1**：核心商业化/事业单位人事流程缺口，应在对应模块封板前补齐。
- **P2**：扩展高校类型时再启用，不阻断当前高职商业化底座。

# 2. 自动一致性扫描摘要

| 检查项 | 扫描结果 | 判断 |
|---|---|---|
| 18 份终极版文件 | 18/18 | 完整 |
| 使用旧 API 根 `/api/hr/v1` | HR01, HR02, HR03, HR04, HR05, HR06, HR07, HR08, HR09 | **冲突** |
| 使用新 API 根 `/api/v1/hr` | HR10, HR11, HR12, HR13, HR14, HR15, HR16, HR17, HR18 | 00 已冻结此方向 |
| 明确出现 PostgreSQL 专属/硬前提 | HR01, HR02, HR03, HR04 | **与项目 MySQL-only 规则冲突** |
| 明确出现 MySQL 生产验收 | HR14, HR15, HR16, HR18 | 后期文档已开始校正 |
| 未显式引用 00 全局合同 | HR01, HR02, HR03, HR04, HR05, HR06, HR07, HR08, HR09, HR10, HR11, HR12, HR13, HR14, HR15, HR16, HR17 | **需要统一补头** |
| HR03 职称生效事件 | `ProfessionalTitleAppointmentEffective` | **与 HR13 不一致** |
| HR13 职称生效事件 | `ProfessionalTitleResultEffective` | 建议设为 canonical |
| HR14 岗位生效事件 | `PositionAppointmentEffective` + `AppointmentEffective` | **一域两个近义 canonical 名** |
| HR01 指标定义 | `MetricDefinitionRegistry` | 与 HR18 Metric Authority 需合并 |
| HR18 指标定义 | `MetricDefinitionVersion` / Metric Registry | 建议作为正式 owner |

# 3. P0-01｜HR01–HR17 没有统一声明 00 是最高合同

### 现状
HR18 已明确：`全局最高合同：00_高校人事系统全局架构与旧系统接管合同.md`。但 HR01–HR17 绝大多数是在 00 之前生成，只按“继承前几册”链式继承；HR16 甚至没有 `前置标准` 头。

### 风险
- 编码 AI 单独拿 HR04/HR05 时，可能不知道后来冻结的 API、Permission、数据库目标、Service Principal、Legal Hold、Global Event 等规则。
- 链式继承会产生“第 12 册知道某规则、第 3 册不知道”的时间差。
- 如果 00 与旧册冲突，没有显式优先级就会出现各自选择。

### 必须补丁
HR01–HR17 每册头部增加统一文本：

```text
> 全局最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`。
> 本册业务 Authority 细节优先于其他业务册，但不得违反 00 的 tenant、API、数据库目标、事件、权限、Legacy、审计、安全和最终生产 Gate。
```

HR18 保持现有写法。

# 4. P0-02｜API 根路径已经分裂成两套

### 扫描结果
- HR01–HR09 大量使用：`/api/hr/v1/...`（扫描命中：HR01, HR02, HR03, HR04, HR05, HR06, HR07, HR08, HR09）。
- HR10 以后逐步使用：`/api/v1/hr/...`（扫描命中：HR10, HR11, HR12, HR13, HR14, HR15, HR16, HR17, HR18）。
- 00 全局合同冻结：`/api/v1/hr/...`。

### 风险
- 前端/移动端/HR17 Gateway/HR18 Drilldown 会出现两套 client base URL。
- 旧 deep link、API gateway、权限匹配、OpenAPI tag、契约测试会分裂。
- 编码 AI 可能在同一仓库继续新增旧路径。

### 裁决
Canonical：

```text
/api/v1/hr/...
```

兼容期允许旧 `/api/hr/v1/...` 作为明确的 Legacy API Adapter/redirect/reverse proxy，但：
- 不得继续新增业务；
- 必须有 deprecation metric；
- 不得在两个路径维护两套 handler；
- 所有新契约测试只以 `/api/v1/hr/...` 为 Authority；
- 旧客户端迁完后删除 adapter。

# 5. P0-03｜生产数据库合同冲突：旧册写死 PostgreSQL，项目规则已经 MySQL-only

### 文档现状
- HR01 H0 写了 `PostgreSQL 迁移一致`。
- HR02 不仅写 PostgreSQL，还把 `daterange + ExclusionConstraint + btree_gist/GIST` 作为推荐有效期不重叠实现。
- HR03 的迁移/搜索索引/assignment overlap 仍带 PostgreSQL 假设。
- HR04 索引优化写 `PostgreSQL 根据真实查询计划优化`。
- 后期 HR14/HR15/HR16/HR18 已加入 MySQL 目标库回归思想。
- 项目 `CLAUDE.md` 交叉核验明确了 MySQL-only：开发、测试、部署、迁移、验收统一 MySQL，并禁止继续新增 PostgreSQL 专属语法。


### 风险
- HR02 的 `daterange/GIST` 直接无法按 MySQL 原样落地。
- AI 会根据旧册设计 PostgreSQL 专属 migration，最终再返工。
- SQLite/PostgreSQL 测试通过不能证明 MySQL 并发/索引/锁语义正确。

### 裁决
00 必须从“如果目标为 MySQL”升级为项目明确的：

```text
Production DB Authority = MySQL
Development/Test/CI/Deploy/Migration Acceptance = MySQL
```

HR01–HR04 中所有 PostgreSQL 文本改为：
- “S0 读取 legacy PostgreSQL 能力仅用于迁移识别，不作为新 Authority 设计约束”；
- `daterange` 改为 `effective_from/effective_to + service validation + row/advisory-equivalent lock + unique/current constraint + concurrency test`；
- 搜索索引按 MySQL collation/generated/hash/index 能力重新设计；
- 所有 migration 在 MySQL 真实实例执行。

**这是当前复审最优先修复项之一。**

# 6. P0-04｜HR04/HR05 的“ADAPT”与 00 的“REWRITE Authority”语义冲突

### 现状
- HR04 头部：`总体接管策略：ADAPT`，同时又写“重建高校招聘业务真相”。
- HR05 头部：`总体接管策略：ADAPT`，同时又写“高校入职权威模型”。
- 00 对 `recruitment`、`onboarding` 的裁决是 `REWRITE`，但说明可以复用 pipeline/UI、task/portal。


### 根因
这里不是业务设计真的冲突，而是一个 `strategy` 字段混进了两层含义：

```text
Authority Strategy
Technical/UI Reuse Strategy
```

### 必须统一
HR04：

```text
Authority Strategy = REWRITE
Legacy Technical Reuse = ADAPT (pipeline/UI/filter/portal where safe)
```
HR05：

```text
Authority Strategy = REWRITE
Legacy Technical Reuse = ADAPT (task/portal/workflow UI where safe)
```
这样 AI 不会误把 Horilla Candidate/Onboarding Stage 当新系统正式 Authority。

# 7. P0-05｜跨域事件名称没有 canonical registry

### 已确认冲突 A：HR03 ↔ HR13
- HR03 写：职称生效接收 `ProfessionalTitleAppointmentEffective`。
- HR13 正式 Outbox 写：`ProfessionalTitleResultEffective`。
- “职称结果”与“岗位聘任”本来已经在 HR13/HR14 明确分域，因此 `ProfessionalTitleAppointmentEffective` 容易再次混淆 Title 与 Appointment。

### 裁决 A
统一 canonical：

```text
ProfessionalTitleResultEffective
ProfessionalTitleResultRevised
ProfessionalTitleResultRevoked
```
HR03/HR14/HR15/HR18 consumer 全部按该名字 + `eventVersion` 订阅。

### 已确认冲突 B：HR14
- HR14 对 HR03 写 `PositionAppointmentEffective`。
- HR14 对 HR15 又写 `AppointmentEffective`。
- 如果这两个是同一个业务事实，不应存在两个近义 canonical；如果一个是 domain event、一个是 derived request，则必须明确类型。

### 裁决 B
建议：

```text
Canonical domain fact: PositionAppointmentEffective
Derived command/request: CompensationReevaluationRequested
```
HR15 不直接依赖模糊 `AppointmentEffective`。

### 全局补丁
- 00 新增 `GlobalEventRegistry`。
- 每事件固定 eventType、eventVersion、owner、consumer、aggregate、payload schema、idempotency、PII classification。
- 所有跨域事件由 registry 生成契约测试；禁止总册各自造同义词。

# 8. P0-06｜Permission namespace 已经分裂

### 现状
- HR01–HR03 主要使用 `hr.dashboard.* / hr.staff.* / hr.organization.*`。
- HR04–HR09 大量使用 `hr04.* / hr05.* / hr06.* / hr07.* / hr08.* / hr09.*`。
- HR13–HR15 又转为 `hr.title.* / hr.appointment.* / hr.payroll.*`。
- 00 只写了抽象格式 `hr.<domain>.<resource>.<action>`，尚未给出所有 domain 的 canonical slug。

### 风险
- 同一角色在不同模块需要三种命名解析规则。
- 迁移 Horilla permissions 时容易出现 alias、重复授权、漏撤权。
- HR17 SELF 与 HR18 field permission 会变得难以统一。

### 裁决
00 冻结 domain slug：

```text
hr.dashboard
hr.organization
hr.staff
hr.recruitment
hr.onboarding
hr.change
hr.contract
hr.external
hr.qualification
hr.development
hr.time
hr.assessment
hr.title
hr.appointment
hr.payroll
hr.exit
hr.self
hr.data
```
旧 `hr04.*` 等通过 PermissionAliasMapping 迁移，Authority code 只保留一套。

# 9. P0-07｜HR01 与 HR18 都在定义 MetricDefinition

### 现状
- HR01 已设计代码级 `MetricDefinitionRegistry`，并保存 owner domain/source/freshness/cache 等。
- HR18 又正式拥有 `MetricDefinition / MetricDefinitionVersion / Population / Dimension / MetricPack`。

这两套如果都实现，就会形成“人事工作台指标口径”和“数据中心指标口径”双主。

### 裁决
正式指标定义 Authority 统一归：

```text
HR18 Metric Registry
```
HR01 变为：

```text
HR18 MetricDefinition consumer
+ HR01 DashboardPresentationConfig
+ Alert/Todo/QuickAction own states
```

HR01 原先 `MetricDefinitionRegistry` 的内容迁到 HR18/共享 Metric Registry；HR01 只保存首页展示布局、优先级、允许 stale 的 UI policy，不再拥有公式和 population。
如果 HR18 尚未施工，HR01 可临时使用 `EmbeddedMetricRegistryAdapter`，但 cutover 后只能投影/兼容。

# 10. P1-01｜正式奖励、处分、复核申诉与人事争议没有业务 Authority

### 18 册现状
- HR03 有 `TalentHonor`，定位是人才/荣誉基础事实展示，明确“复杂人才项目申报过程不在 HR03”。
- HR12 有考核结果申诉；HR13 有职称复核/申诉；HR14 有聘任异议。
- HR16 出现“开除/解除”结果型离校，但没有完整处分调查、权限、程序、处分决定、复核/申诉 Authority。
- 没有发现统一的 `PersonnelRewardCase / DisciplinaryCase / PersonnelAppealCase / PersonnelDisputeCase`。


### 外部制度校正
这是实际事业单位人事流程，不是功能想象：现行《事业单位工作人员处分规定》覆盖处分种类、权限、程序、复核和申诉；《事业单位人事管理条例》明确工作人员可对考核结果、处分决定申请复核/申诉，也明确人事争议处理；另有《事业单位工作人员奖励规定》规定正式奖励流程和材料入档。

### 设计补丁：不新增 HR19
建议新增一个**跨域 Personnel Decision capability**，但挂入现有体系：

```text
HR03：正式 PersonnelDecision Fact / RewardFact / DisciplinaryFact 历史 Authority
HR03 内部新增非菜单服务：PersonnelDecisionCase
HR17-05：本人依法/按政策可见的通知、复核/申诉入口
HR15：仅消费一次性奖励/扣发等合法薪酬依据，不拥有奖励决定
HR14：降低岗位等级等影响必须经过自己的正式岗位动作
HR16：开除/解除等只有正式决定生效后才进入离校编排
HR18：只消费 FINAL/EFFECTIVE 结果和法定统计
```
最低模型：

```text
PersonnelDecisionPolicyVersion
PersonnelRewardCase / RewardDecision
DisciplinaryCase / DisciplinaryDecision
ReviewAppealCase
PersonnelDisputeReference
DecisionEvidenceRef
DecisionEffect
DecisionRevision / Revocation
```
必须有回避、证据、程序、告知、复核/申诉、不可原地覆盖、档案回写和 downstream effect。

# 11. P1-02｜干部/教职工人事档案边界仍然模糊

### 现状
- HR03-05 是“人事材料档案”，重点是材料类型、版本、核验、敏感下载和关联事实；它明确不是网盘。
- HR16-05/06 管档案转递过程与离退档案。
- 但 18 册没有明确谁管理正式干部/教职工人事档案的目录、组卷、材料鉴别/收集、查阅审批、借阅利用、数字化版本、转递回执、保管状态。


### 外部校正
《干部人事档案工作条例》把干部人事档案作为组织人事管理中的正式历史记录；近年高校仍持续单独采购人事档案数字化/档案查询利用系统，说明这不是简单“附件上传”。

### 裁决：两种方案二选一，必须在 00/HR03/HR16 明写
**推荐当前单人开发路线：外部 ArchiveProvider 边界，不再造完整档案馆系统。**

```text
HR03-05：Material/Evidence + PersonnelFileCatalogProjection
ArchiveProvider：正式卷宗、目录、组卷、借阅/查阅、数字化原件保管
HR16：TransferCase + Receipt/Reconciliation
HR17：本人依法/按政策可申请的档案服务入口
HR18：只拿允许上报的结构化事实
```
若学校没有独立档案系统，再将“轻量 Personnel File Authority”作为 HR03-05 的四级能力开关，不新增三级菜单。

# 12. P1-03｜HR15 名称叫“薪酬福利”，但职业年金/福利计划缺失

### 现状
HR15 六模块覆盖薪酬档案、薪资规则、月度工资、调资津补贴、社保公积金、工资条/财务对接；全文没有职业年金、企业/补充年金、补充医疗/商业保险、福利计划等明确模型。

### 外部校正
机关事业单位存在正式职业年金制度；《事业单位人事管理条例》也明确事业单位工作人员享受国家规定的福利待遇。

### 必须补入 HR15，不新增模块
优先放入 HR15-05 + HR17-04：

```text
StatutoryBenefitAccount
OccupationalAnnuityAccount / ContributionFact
SupplementaryBenefitPlan
BenefitEnrollment
Employer/Employee ContributionRuleVersion
BenefitStatement
ProviderReceipt / Reconciliation
```
如果学校实际由外部社保/年金平台管理，则 HR15 保留 eligibility/configuration/statement/receipt projection，不自己伪造待遇核定。

# 13. P1-04｜早期 S0–Sx 施工阶段不统一

### 自动扫描
| 模块 | 当前最后阶段 |
|---|---:|
| HR01 | S9 |
| HR02 | S11 |
| HR03 | S12 |
| HR04 | S12 |
| HR05 | S12 |
| HR06 | S12 |
| HR07 | S13 |
| HR08 | S13 |
| HR09 | S13 |
| HR10 | S13 |
| HR11 | S13 |
| HR12 | S13 |
| HR13 | S13 |
| HR14 | S13 |
| HR15 | S13 |
| HR16 | S13 |
| HR17 | S13 |
| HR18 | S13 |

HR01 早期为 S0–S9，HR02 为 S0–S11，HR03–HR06 为 S0–S12；HR07 后开始逐渐使用 S0–S13。

### 风险
- 编码 AI 会把“最后一个 S”误当同一语义，但各册的 Cutover、Legacy、全量质量、最终封板落在不同编号。
- 总控自动化无法统一判断阶段完成度。

### 裁决
不要求重写早期全部正文，只在每册新增 `PhaseCompatibilityMap`：

```text
LOCAL_PHASE -> GLOBAL_PHASE
```
全系统统一最终语义至少包含：

```text
S0 Baseline
S1 A0/Common Contracts
S2 Authority Foundation
S3–S9 Domain Delivery (按模块拆)
S10 Legacy/Migration
S11 Full Quality
S12 Authority Cutover
S13 Final Seal
```
早期本地编号可以保留，但总控以 Global Phase 判断。

# 14. P1-05｜HR16 头部缺少前置标准继承

HR16 明明依赖 HR02/03/07/11/12/14/15/IAM/资产/教务/科研/档案等，但头部没有像 HR15、HR17 那样写 `前置标准：继承...`。

补：

```text
> 全局最高合同：00_高校人事系统全局架构与旧系统接管合同.md
> 前置标准：继承 HR01–HR15 的 A0、API、权限/数据范围、文件安全、异步任务、审计、可观测性、Excel、幂等、事务、Outbox、规则版本、Legacy 退出和 AI 施工纪律。
```

# 15. P1-06｜00 本身还需要三处“从抽象变成可执行”的升级

- **数据库**：当前 00 仍写“若目标为 MySQL”；结合项目 MySQL-only 规则，应直接冻结 MySQL 为生产/开发/测试/迁移 Authority。
- **Permission Registry**：00 只有格式，没有 18 domain slug 全表；应加入本报告第 8 节 canonical slug。
- **Event Registry**：00 只有命名原则，没有跨域 canonical event 清单；应加入 HR03/06/07/09/10/11/12/13/14/15/16 的正式事件表和 schemaVersion。

这三处一补，00 才真正能成为“拿给 AI 后不靠猜”的系统宪法。

# 16. P2｜不阻断当前高职主战场，但以后扩综合大学时要做范围决策

下面不是当前 18 册的 P0/P1 漏洞，暂时不要为了“显得全”就全部开发。

| 能力 | 当前 18 册情况 | 建议 |
|---|---|---|
| 准聘/长聘、Tenure-track | HR12 可扩展考核类型，但未正式建模 | 综合/研究型大学再加 RulePack/Term Track |
| 博士后管理 | 招聘仅零散提及 | 研究型高校商业版本独立能力池 |
| 因私出访/护照证照 | HR03 仅基础证件事实 | 有组织部/国际处需求再建申请/审批/归还闭环 |
| 干部任免/中层干部 | HR02/HR14 可表达管理岗位，但无干部专门流程 | 若客户把组织干部工作纳入合同，再做专门 Policy/Case |
| 外籍教职工工作许可/居留 | 现有入职可扩材料 | 国际化高校再加证照有效期/外事 Provider |
| 工伤认定/职业健康 | HR11/HR15 有零散关联 | 优先对接社保/校医院/外部业务，不在当前重建权威 |

近期高校采购中确实可看到准聘考核、因私出访、博士后等扩展，但这些明显偏综合/研究型高校，不应破坏当前高职商业化主线。

# 17. 18 册逐册复审结论

## HR01

- P0：新增 00 最高合同头。
- P0：`/api/hr/v1` 统一到 `/api/v1/hr`。
- P0：去掉 PostgreSQL H0 硬绑定，按 MySQL-only 执行。
- P0：`MetricDefinitionRegistry` Authority 迁 HR18；HR01 只保留 DashboardPresentation/Alert/Todo/QuickAction。
- P1：S0–S9 增 PhaseCompatibilityMap。

## HR02

- P0：新增 00 最高合同头。
- P0：PostgreSQL daterange/GIST/ExclusionConstraint 改为 MySQL 可落地的 effective interval + transaction/lock/constraint。
- P0：API/Permission canonical 化。
- P1：S0–S11 增 Global Phase 映射。
- 业务结构无需新增三级模块。

## HR03

- P0：新增 00；API/Permission canonical 化；移除 PostgreSQL 专属假设。
- P0：职称事件改 `ProfessionalTitleResultEffective/Revised/Revoked`。
- P1：承接 PersonnelDecision 正式奖励/处分结果与复核申诉事实，或明确外部 Provider。
- P1：HR03-05 明确 Personnel File/ArchiveProvider 边界。
- P1：S0–S12 映射 S13 Final Seal。

## HR04

- P0：`Authority Strategy=REWRITE; Technical Reuse=ADAPT`。
- P0：API canonical 化；旧路径只兼容。
- P0：Permission namespace 从 `hr04.*` 迁 canonical。
- P0：PostgreSQL query-plan 描述改目标 MySQL。
- P1：继承 00；Global Phase 映射。

## HR05

- P0：`Authority Strategy=REWRITE; Technical Reuse=ADAPT`。
- P0：API canonical 化；Permission alias migration。
- P1：补 00 最高合同；Global Phase 映射。
- Onboarding 业务主链本身完整。

## HR06

- P0：补 00；API/Permission canonical。
- P1：Global Phase 映射。
- 与 HR14 管正式岗位聘任、HR16 管离校的边界已清楚，不需扩大为万能人事流程。

## HR07

- P0：补 00；API/Permission canonical。
- P1：Event 必须进入 GlobalEventRegistry。
- 合同与 EmploymentRelationship、HR14 岗位聘任的边界总体正确。

## HR08

- P0：补 00；API/Permission canonical。
- P1：External Engagement 相关事件进入 GlobalEventRegistry。
- 正式员工/外聘/返聘分层设计保持。

## HR09

- P0：补 00；API/Permission canonical。
- P1：资格结果/撤销事件纳入全局 registry。
- 教师资格与双师型分层正确。

## HR10

- P0：补 00。
- P1：统一 Permission/Event registry；保持 `/api/v1/hr`。
- 培训完成/企业实践/学历事实边界正确。

## HR11

- P0：补 00。
- P1：closed/frozen time facts 与 payroll/assessment consumer event 加入 registry。
- 原始打卡≠考勤结论、请假≠扣款的边界正确。

## HR12

- P0：补 00。
- P1：考核申诉只解决“考核结果”；不要误当统一人事处分申诉。
- P1：正式 Result events 纳入 GlobalEventRegistry。

## HR13

- P0：补 00。
- P0：Canonical event 固定为 `ProfessionalTitleResultEffective/Revised/Revoked`。
- 职称≠岗位聘任、职称通过≠涨薪的边界正确。

## HR14

- P0：补 00。
- P0：统一 `PositionAppointmentEffective`，废除/别名化模糊 `AppointmentEffective`。
- P0：Permission canonical。
- HR02 quota / HR03 assignment / HR14 appointment / HR15 compensation 四账思路保留。

## HR15

- P0：补 00；Permission canonical。
- P1：HR15-05 增职业年金与福利计划/外部 Benefit Provider。
- P1：消费奖励决定只算钱，不拥有奖励决定 Authority。
- 财务总账/实际付款边界保持。

## HR16

- P0：补 00 + HR01–HR15 前置标准头。
- P1：正式处分导致开除/解除必须消费 PersonnelDecision，不在 HR16 自己判处分。
- P1：ArchiveProvider/PersonnelFile Transfer receipt 边界补全。
- 退休预测/批准/生效、离校/账号停用等日期分离设计正确。

## HR17

- P0：补 00。
- P1：HR17-05 增 Personnel Reward/Discipline notice、复核/申诉/争议服务入口（只做 Experience，不做事实 Authority）。
- P1：HR17-04 增职业年金/福利 statement SELF 展示。
- SELF resolver、多关系切换、敏感 reauth 设计保持。

## HR18

- P0：保持 00 最高合同。
- P0：正式接管 MetricDefinition Authority，并给 HR01 提供 Metric Provider。
- P1：新增 PersonnelDecision/职业年金/档案来源后，补相应 Dataset/Submission mapping。
- 现有正式上报、Snapshot、Receipt、Correction chain 设计保持。

# 18. 最终 Canonical Contract Freeze（本复审建议直接写回 00）

## 18.1 API
```text
Canonical API Base = /api/v1/hr
Legacy Adapter = /api/hr/v1 (read/redirect/compat only, sunset)
```

## 18.2 Database
```text
Production / Dev / Test / CI / Migration Acceptance = MySQL
Legacy PostgreSQL syntax is migration knowledge, not new Authority design.
```

## 18.3 Authority Strategy
```text
strategy.authority = KEEP | ADAPT | REWRITE | NEW
strategy.legacy_technical_reuse = KEEP | ADAPT | NONE
strategy.legacy_projection = PROJECT | READONLY | NONE
```

## 18.4 Event
```text
ProfessionalTitleResultEffective
ProfessionalTitleResultRevised
ProfessionalTitleResultRevoked
PositionAppointmentEffective
CompensationReevaluationRequested
StaffActivated
PersonnelChangeEffective
ExitEffective
RetirementEffective
PayrollFinalized
```
所有事件必须再加 `eventVersion`，具体 payload 由 GlobalEventRegistry 冻结。

## 18.5 Metric
```text
Formal MetricDefinition Authority = HR18
HR01 = Metric Consumer + Dashboard Presentation Authority
```

## 18.6 Permission
按第 8 节 18 个 canonical domain slug 固定；旧 `hr04/hr05...` 做 alias migration。

# 19. 三个业务空洞的最小施工包

## 19.1 Personnel Decision 最小包
- PolicyVersion；RewardCase/Decision；DisciplinaryCase/Decision；ReviewAppealCase；evidence；recusal；notice；revision/revocation；downstream effects。
- 禁止把年度考核不合格自动变处分；禁止处分自动改岗位/工资/离校。
- HR14/15/16 各自根据正式决定再走本域流程。

## 19.2 Personnel File 最小包
- 若外部档案系统：ArchiveProvider + FileCatalogProjection + AccessRequestRef + TransferReceipt + Reconciliation。
- 若无外部系统：HR03-05 增轻量 dossier/catalog/version/access/borrow/transfer，但不做通用档案馆。
- HR16 只编排转递，不成为档案正文 Authority。

## 19.3 Benefit 最小包
- 职业年金 Account/Contribution/Statement；补充福利 Plan/Enrollment；Provider receipt/reconcile。
- HR15 管计算/配置/对账事实，外部基金/社保平台仍是相应待遇外部 Authority。
- HR17 只提供本人可见权益。

# 20. 外部校正依据（与 18 册内部复审分开）

这些来源只用于证明第 10–12 节所列业务不是“为了加功能而加功能”：

1. 《事业单位人事管理条例》：含工资福利、人事争议、考核/处分复核申诉、回避等。
   https://www.mohrss.gov.cn/SYrlzyhshbzb/fwyd/SYkaoshizhaopin/zyhgjjgsydwgkzp/xgzc/201711/t20171110_281424.html

2. 《事业单位工作人员处分规定》（人社部发〔2023〕58号）：处分种类、权限、程序、复核/申诉。
   https://chinajob.mohrss.gov.cn/c/2023-11-27/391549.shtml

3. 《事业单位工作人员奖励规定》（人社部规〔2018〕4号）：正式奖励制度、程序、材料归档。
   https://www.ndrc.gov.cn/fggz/jyysr/jysrsbxf/201812/t20181227_1124201.html

4. 《机关事业单位职业年金办法》：事业单位工作人员补充养老保险制度。
   https://www.ssf.gov.cn/portal/zcfg/nbgzzd/webinfo/2015/04/1632636003907578.htm

5. 《干部人事档案工作条例》：正式干部人事档案治理。
   https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/201811/t20181128_780785.html

6. 2025–2026 高校采购校正：高校持续采购干部人事档案数字化/档案系统；西安交通大学 2025 HR 四期还包含准聘考核、岗位聘任、因私出访、博士后、退休、同行评议等扩展模块。
   https://info.xjtu.edu.cn/info/1045/44425.htm
   https://news.sxufe.edu.cn/info/1023/66794.htm
   https://www.pzhu.edu.cn/info/1481/109151.htm

# 21. 不建议补的“伪遗漏”

- 不新增万能审批中心作为第 19 域：审批技术可共用，但决定仍属于业务 Authority。
- 不新增万能文件中心：文件 bytes/安全 Provider 共用，业务材料归源域。
- 不新增万能数据中台：HR18 已承担 HR 数据目录/交换/上报，不做全校通用湖仓。
- 不把科研/教务复制进 HR：只用 Provider/EvidenceRef。
- 不把财务总账复制进 HR15：HR15 是 payroll，应付/工资事实与 posting package；财务仍负责总账/资金/实际付款。
- 不把档案馆完整功能硬塞 HR03：优先 ArchiveProvider。
- 不把干部组织工作、博士后、国际人员等为了“看起来全”现在全部施工。

# 22. 建议补丁施工顺序

```text
PATCH-00  更新 00：MySQL-only + API + Permission + Event Registry + Strategy 两层语义
PATCH-01  HR01–HR17 批量补“00 最高合同”头
PATCH-02  全仓 API /api/hr/v1 → /api/v1/hr + Legacy Adapter
PATCH-03  PostgreSQL 专属设计清理 → MySQL temporal/locking/index contract
PATCH-04  PermissionAliasMapping + canonical permission migration
PATCH-05  GlobalEventRegistry + HR03/13/14/15 event rename
PATCH-06  HR01 MetricDefinition → HR18 Metric Authority
PATCH-07  PhaseCompatibilityMap / Global S0–S13
PATCH-08  Personnel Decision（奖励/处分/申诉）补 HR03/17/14/15/16/18
PATCH-09  ArchiveProvider / Personnel File 边界补 HR03/16/17
PATCH-10  职业年金/福利补 HR15/17/18
PATCH-11  18 册 Cross-Document Contract Tests
PATCH-12  再进入 HR01→HR18 真实编码施工
```

原则：**先修合同，再写代码；否则越施工越难统一。**

# 23. Cross-Document Contract Tests（新增总验收）

- API base：新 Authority endpoint 100% `/api/v1/hr`；旧路径只 adapter。
- DB：新 migration 无 PostgreSQL-only syntax；MySQL full migration/test green。
- Permission：每个 action 只能解析到一个 canonical permission；alias 不重复授权。
- Event：producer/consumer schema contract test；eventType/eventVersion 一致。
- Title：HR13 发 `ProfessionalTitleResultEffective`，HR03/14/15/18 正确消费。
- Appointment：HR14 发 `PositionAppointmentEffective`；HR15 通过明确 request/event 重算。
- Metric：同一 metricKey 只有一个 HR18 definitionVersion；HR01 值与 HR18 drilldown 守恒。
- Tenant：每个跨域 Provider/Event/Job 带 tenant；无 tenant fail-closed。
- As-of：随机历史日期跨 HR02/03/07/09/10/12/13/14/15/16/18 查询不被 current 值污染。
- Legacy：Authority cutover 后 legacy formal write attempt = 0。
- Personnel Decision：处分/奖励结果不可自动直写工资/岗位/离校。
- Archive：Transfer 必须有 external/internal receipt，不能 checkbox 完成。
- Benefit：职业年金/福利外部回执与 HR15 projection 对账。
- Restore：备份恢复后重建 projection，Outbox/Inbox/External receipt 不重复正式动作。

# 24. 最终封板口径

18 份总册经过本报告补丁后，才允许进入正式施工总控：

```text
GLOBAL ARCHITECTURE CONTRACT READY
HR01 ... HR18 DOCUMENT CONTRACTS CONSISTENT
NO P0 DOCUMENT CONFLICT
P1 BUSINESS GAPS ASSIGNED TO AUTHORITIES
READY FOR IMPLEMENTATION
```

如果下面任一仍存在：
- 两套 API 根；
- PostgreSQL 专属新 Authority migration；
- HR04/05 ADAPT/REWRITE 语义不清；
- 事件同义词；
- Permission 三套 namespace；
- HR01/HR18 两套 MetricDefinition；
- 奖励/处分/申诉没有 Authority；
- 职业年金/福利仍完全空白；
- 档案正文/目录/转递 Authority 仍无人负责；

则只能：

```text
DOCUMENT SET NOT READY
blocking:
- <精确合同冲突>
```

# 25. 一句话最终结论

> **HR01–HR18 的大框架不用推翻、也不用加 HR19；先修 7 个 P0 跨册合同，再把奖惩处分/人事申诉、人事档案边界、职业年金与福利 3 个真实 P1 空洞补回现有模块，这套 18 册才真正达到“可以放心交给编码 AI 连续施工”的强度。**
