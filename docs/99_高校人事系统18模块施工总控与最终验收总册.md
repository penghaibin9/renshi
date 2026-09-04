# 99_高校人事系统18模块施工总控与最终验收总册

> 产品：跃科高校人事管理与教师发展系统  
> 文件定位：HR01–HR18 正式施工的唯一总控路线图；**不是 HR19**  
> 最高合同：`00_高校人事系统全局架构与旧系统接管合同.md`
> 业务事实源：HR01–HR18 各《施工总册_终极版》  
> 复审依据：`HR01-HR18_总一致性与遗漏复审报告_终极版.md`  
> 版本：V1.0 最终施工总控版  
> 编写日期：2026-08-09  
> 核心原则：**先统一合同，再按依赖施工；单模块全绿不等于系统可交付。**

# 0. 文件定位

本文件不是 HR19，不新增业务二级模块。

已有文档职责：
- `00_高校人事系统全局架构与旧系统接管合同.md`：全系统宪法。
- `01_HR01`～`18_HR18`：各业务域施工事实源。
- `HR01-HR18_总一致性与遗漏复审报告_终极版.md`：检查 18 册冲突与遗漏。
- **本文件**：把上述文档变成编码 AI 可连续执行的施工顺序、统一 Gate 与最终交付路线。

以后能由代码自动生成的 API、Event、Permission、Data Dictionary、UAT 等，不提前维护第二套手工真相。

# 1. 施工总原则

1. 不增加 HR19。
2. 先修文档合同，再写 Authority 代码。
3. 业务事实只能由对应 Authority 写。
4. 生产/开发/测试/CI/迁移验收统一按 MySQL。
5. Canonical API Base 固定 `/api/v1/hr`。
6. 跨域事件进入 GlobalEventRegistry。
7. 权限进入 CanonicalPermissionRegistry。
8. 正式 MetricDefinition Authority = HR18；HR01 只消费。
9. 无 tenant/scope/provider 时 fail-closed。
10. Authority Cutover 后禁止 silent legacy fallback。
11. FINAL/EFFECTIVE/CLOSED 事实不原地覆盖。
12. 异步导出/批量/交换/报送必须真实异步。
13. 每个模块独立 READY，但全系统还必须通过跨域 E2E、MySQL、安全、恢复和 Legacy Cutover。

# 2. 正式编码前 PATCH-00 → PATCH-12

| 编号 | 必做任务 | 目标 |
|---|---|---|
| PATCH-00 | 更新 00 总合同 | 冻结 MySQL-only、API、Permission、Event、接管策略双层语义 |
| PATCH-01 | HR01–HR17 补 00 最高合同头 | 所有业务册继承同一全局合同 |
| PATCH-02 | 统一 API | `/api/hr/v1` → `/api/v1/hr`，旧路径仅 Legacy Adapter |
| PATCH-03 | 清理 PostgreSQL 专属新设计 | HR01–HR04 的 daterange/GIST 等改 MySQL 可落地方案 |
| PATCH-04 | 统一 Permission | `hr04.*` 等旧 namespace 迁 canonical permission |
| PATCH-05 | 统一 Event | HR03/13、HR14/15 等事件命名与 schema contract |
| PATCH-06 | 统一 Metric Authority | HR01 MetricDefinition → HR18；HR01 只做 Dashboard Presentation |
| PATCH-07 | 统一 Global Phase | 旧册 S0–S9/S11/S12 映射为统一 S0–S13 |
| PATCH-08 | 补 Personnel Decision | 奖励、处分、复核申诉、人事争议补回现有域 |
| PATCH-09 | 补 Personnel File 边界 | ArchiveProvider / HR03 / HR16 / HR17 责任明确 |
| PATCH-10 | 补职业年金与福利 | HR15 / HR17 / HR18 |
| PATCH-11 | Cross-Document Contract Tests | API/Event/Permission/Metric/Tenant/As-of/Legacy 自动契约测试 |
| PATCH-12 | Documentation Baseline | 合同全部一致后才进入业务大施工 |

Gate：

```text
DOCUMENT CONTRACT BASELINE READY
```

未达到该 Gate，不进入 HR02/HR03 Authority 大改。

# 3. 全系统施工依赖 DAG

```text
                 00 / Global A0
                       │
                 ┌─────┴─────┐
                 ▼           ▼
                HR02        HR03
                 └─────┬─────┘
                       ▼
                      HR04
                       ▼
                      HR05
                 ┌─────┴─────┐
                 ▼           ▼
                HR06        HR07
                 │            │
              ┌──┴──────┬────┘
              ▼         ▼
             HR08      HR09
                        │
                 ┌──────┴──────┐
                 ▼             ▼
                HR10          HR11
                 └──────┬──────┘
                        ▼
                       HR12
                        ▼
                       HR13
                        ▼
                       HR14
                        ▼
                       HR15
                        ▼
                       HR16
                  ┌─────┴─────┐
                  ▼           ▼
                 HR17        HR18
```

HR01 可较早建设 UI/Control Center 壳，但正式指标必须等待 HR02/HR03/HR18 口径。

# 4. 推荐施工波次 W0–W8

| 波次 | 范围 | 施工内容 |
|---|---|---|
| W0 | 全局底座 | Tenant、Auth/Scope、API/Error、Audit、Files、Jobs、Outbox/Inbox、MySQL CI |
| W1 | 事实底座 | HR02 + HR03 |
| W2 | 入人主链 | HR04 + HR05 + HR07 |
| W3 | 人事变化 | HR06 + HR08 |
| W4 | 教师发展与时间 | HR09 + HR10 + HR11 |
| W5 | 评价裁决 | HR12 + HR13 + HR14 |
| W6 | 薪酬离退 | HR15 + HR16 |
| W7 | 统一体验与数据 | HR17 + HR18 |
| W8 | 系统封板 | HR01 全 Authority、跨域 E2E、安全、恢复、性能、商业验收 |

原则：强依赖链不抢跑。

# 5. Global Phase S0–S13

| 阶段 | 含义 |
|---|---|
| S0 | Baseline Audit：只读仓库、旧表、路由、权限、signals、CI、DB、Provider |
| S1 | A0/Common：tenant、scope、API、permission、files、audit、jobs、idempotency |
| S2 | Authority Foundation：模型、effective-dated、RuleVersion、Snapshot、Provider |
| S3–S5 | 模块核心业务链 |
| S6 | 高风险动作：final/effect/correct/revoke/concurrency |
| S7 | Excel / Bulk / Async |
| S8 | 管理 UI / Mobile / SELF |
| S9 | Observability / Data Quality |
| S10 | Legacy Mapping / Backfill / Dual Read |
| S11 | MySQL / Security / Performance / E2E / A11y / Visual |
| S12 | Authority Cutover / Freeze Legacy Writes / Rollback Rehearsal |
| S13 | Final Seal |

早期文档原有本地 Phase 编号可以保留，但必须增加 `LOCAL_PHASE → GLOBAL_PHASE` 映射。

# 6. Canonical API Registry

全系统唯一新 API Root：

```text
/api/v1/hr
```

一级资源建议：

```text
/api/v1/hr/dashboard
/api/v1/hr/organizations
/api/v1/hr/staff
/api/v1/hr/recruitment
/api/v1/hr/onboarding
/api/v1/hr/changes
/api/v1/hr/contracts
/api/v1/hr/external
/api/v1/hr/qualifications
/api/v1/hr/development
/api/v1/hr/time
/api/v1/hr/assessments
/api/v1/hr/titles
/api/v1/hr/appointments
/api/v1/hr/payroll
/api/v1/hr/exit
/api/v1/hr/self
/api/v1/hr/data
```

旧 `/api/hr/v1/...` 只能：
- Adapter / redirect；
- 有 deprecation metric；
- 不新增业务 handler；
- 客户端迁完后删除。

# 7. Canonical Permission Registry

| 模块 | Prefix |
|---|---|
| HR01 | `hr.dashboard` |
| HR02 | `hr.organization` |
| HR03 | `hr.staff` |
| HR04 | `hr.recruitment` |
| HR05 | `hr.onboarding` |
| HR06 | `hr.change` |
| HR07 | `hr.contract` |
| HR08 | `hr.external` |
| HR09 | `hr.qualification` |
| HR10 | `hr.development` |
| HR11 | `hr.time` |
| HR12 | `hr.assessment` |
| HR13 | `hr.title` |
| HR14 | `hr.appointment` |
| HR15 | `hr.payroll` |
| HR16 | `hr.exit` |
| HR17 | `hr.self` |
| HR18 | `hr.data` |

旧 `hr04.* / hr05.* ...` 建 `PermissionAliasMapping` 迁移，不再继续扩展。

# 8. Global Event Registry 最低冻结

至少统一以下正式跨域事件：

```text
StaffActivated
PersonnelChangeEffective
ContractEffective
ContractTerminated
QualificationResultEffective
DevelopmentFactVerified
TimePeriodClosed
AssessmentResultFinalized
ProfessionalTitleResultEffective
ProfessionalTitleResultRevised
ProfessionalTitleResultRevoked
PositionAppointmentEffective
CompensationReevaluationRequested
PayrollFinalized
ExitEffective
RetirementEffective
```

其中：

```text
HR13 → ProfessionalTitleResultEffective
HR14 → PositionAppointmentEffective
HR14/HR03/HR06 → CompensationReevaluationRequested → HR15
```

禁止继续同时使用：
- `ProfessionalTitleAppointmentEffective`
- 模糊 `AppointmentEffective`

每事件必须冻结：
`eventVersion / owner / consumers / aggregate / tenant / effectiveAt / payload schema / PII classification / idempotency / replay rule`。

# 9. Metric Authority

正式指标只有一个定义 Authority：

```text
HR18 = MetricDefinition / Population / Dimension / as-of Authority
HR01 = Metric Consumer + Dashboard Presentation Authority
```

HR01 只能拥有：
- 首页布局；
- 卡片顺序；
- 角色化展示；
- Alert / Todo / QuickAction；
- stale 展示政策。

HR01 不再拥有另一套人数、流动率、职称结构等公式。

# 10. 三个 P1 业务补丁的最终归属

### 10.1 Personnel Decision

- HR03：正式 Reward / Disciplinary Decision Fact、Review/Appeal 基础事实。
- HR17：本人通知与复核/申诉服务入口。
- HR14：岗位影响必须再走 HR14 正式业务。
- HR15：只消费合法薪酬 effect。
- HR16：只有正式解除/开除决定生效后进入离校。
- HR18：只消费 FINAL/EFFECTIVE 结果。

禁止处分直接跨域 UPDATE 岗位、工资、离校。

### 10.2 Personnel File

优先：

```text
HR03-05 Material/Evidence + FileCatalogProjection
          ↓
ArchiveProvider = 正式卷宗/目录/查阅/借阅/数字化原件
          ↓
HR16 TransferCase + Receipt/Reconciliation
          ↓
HR17 本人档案服务入口
```

学校无独立档案系统时再启用 HR03-05 轻量档案 Authority Feature Pack。

### 10.3 Occupational Annuity / Benefit

- HR15-05：职业年金账户/缴费、福利计划、Enrollment、Provider Receipt/Reconciliation。
- HR17-04：本人权益 Statement。
- HR18：统计与上报映射。
- 外部基金/社保平台仍是实际待遇核定外部 Authority。

# 11. MySQL-only 总合同

1. Dev / Test / CI / Migration / Deploy Acceptance 全部按 MySQL。
2. 禁止新增 PostgreSQL daterange/GIST/ExclusionConstraint 专属 Authority 设计。
3. Temporal overlap 使用 `effective_from/effective_to + transaction lock + unique/current invariant + concurrency test`。
4. 金额/比例 Decimal，禁止 Float。
5. UTF8MB4，统一 collation。
6. JSON 只用于配置/快照，不代替正式关系建模。
7. migration 从 clean DB 和 previous baseline 均要通过。
8. row locking、deadlock retry、idempotency 必测。
9. 大查询 EXPLAIN + index regression。
10. 备份恢复在真实 MySQL 演练。

# 12. A0 多学校隔离总 Gate

- 所有 Authority 表有 tenant_id 或不可绕过 tenant FK。
- 前端传 tenant_id 不是授权依据。
- list/search/autocomplete/export/dashboard/drilldown/files/jobs/events 同 scope。
- 跨 tenant FK 写入失败。
- Job/Event 明确 tenant context。
- 无 tenant fail-closed。
- 平台运营默认无学校人事/工资/档案权限。
- Saved Report、Export Artifact、Download Ticket 也必须 tenant scoped。
- IDOR / search / file / export / callback 做跨学校负向测试。

# 13. 跨模块真实 E2E

必须至少跑以下 12 条：

1. HR02 Position → HR04 招聘 → HR05 入职 → HR03 Staff/Relationship/Assignment。
2. HR03 Relationship → HR07 Contract → HR17 我的合同。
3. HR06 异动 → HR03 Assignment history → HR02 occupancy → HR15 reevaluation → HR18 as-of。
4. HR10 verified 企业实践/培训 → HR09 双师证据 → HR12 考核证据。
5. HR11 TimePeriodClosed → HR15 PayrollFinalized → HR17 Payslip → HR18 cost。
6. HR12 Final → HR13 Title Effective → HR14 Appointment Effective → HR15 Compensation Review。
7. HR16 RetirementEffective → HR03 关系关闭 → HR14 聘任关闭 → HR15 final settlement → HR17 retiree。
8. HR16 ExitEffective → IAM/资产/交接 → HR15 final settlement → HR18 turnover。
9. 今天改变组织/职称/岗位/工资后，2024/2025 as-of 仍为当时事实。
10. HR02–HR16 → HR18 Snapshot → Validate → Approve → Send → Receipt → Correction。
11. DisciplinaryDecision 生效后，HR14/15/16 各走自己流程，不自动跨域改事实。
12. HR16 档案转递 → ArchiveProvider → Receipt → Reconciliation → Closed。

# 14. Failure Injection 必测

必须模拟：
- Provider 500 / timeout；
- 请求超时但业务实际成功；
- 重复 webhook / event；
- worker down；
- Outbox 积压；
- MySQL deadlock；
- 最后一个岗位额度并发竞争；
- payroll finalize 重复请求；
- object storage outage；
- IAM 停权失败；
- 电子签署成功但 callback 丢失；
- payment / finance partial success；
- HR18 SENT 长期无 receipt；
- restore 后 projection 缺失；
- legacy write 被旧书签调用；
- 跨 tenant 猜 ID；
- 权限缓存未失效。

绝不能造成重复 Staff、Contract、Appointment、Payroll、Submission 或跨租户泄露。

# 15. Excel / Bulk 统一流水线

```text
TemplateVersion
→ Upload
→ Staging
→ Validation
→ Preview
→ Error Workbook
→ Confirm
→ Async Job
→ Per-item Result
→ Audit / Export Ledger
```

禁止：
- Excel 直接覆盖 FINAL/EFFECTIVE；
- 绕审批；
- 跨 tenant；
- 同步处理大批量；
- 空值静默清敏感事实；
- 高敏导出无字段权限和审计。

# 16. 文件与高敏数据总 Gate

- Private Object Storage。
- Download Ticket + short TTL signed URL。
- 身份证、银行卡、工资、处分、档案字段级权限。
- 敏感 Reveal 可要求 MFA/Reauth。
- Download/Reveal/Export 全审计。
- MIME/extension/size/scan/hash。
- Legal Hold。
- 日志不写高敏值和永久 URL。
- 备份必须包含对象存储与密钥恢复能力。

# 17. Observability 总 Gate

统一监控：
- HTTP p95/error；
- 403/tenant denial；
- Provider availability；
- Outbox lag / Inbox duplicate；
- Job backlog/failure；
- legacy formal write attempts；
- projection/reconciliation drift；
- data quality P0/P1；
- payroll partial/failure；
- exit downstream failure；
- HR18 submission reject/correction；
- sensitive reveal/export。

生产正常不能只看 `/health=200`。

# 18. Legacy Cutover

所有模块统一：

```text
LEGACY_ACTIVE
→ NEW_STAGING
→ DUAL_READ_COMPARE
→ SHADOW_EXECUTION
→ FREEZE_LEGACY_FORMAL_WRITES
→ NEW_AUTHORITY
→ LEGACY_READONLY_PROJECTION
→ POST_CUTOVER_CLEANUP
```

Cutover 后：
- legacy formal write attempts 必须为 0；
- 旧 deep link redirect；
- no silent fallback；
- rollback 回入口/consumer，不删除已发生的新正式事实。

# 19. Backup / Restore Gate

正式交付前必须：
- MySQL backup；
- object storage backup；
- key/config/migration state backup；
- 完整 restore drill；
- 恢复后 rebuild projection；
- Outbox/Inbox duplicate check；
- HR02↔03↔14 对账；
- HR07↔03 对账；
- HR15↔Finance 对账；
- HR16↔IAM 对账；
- HR18 Submission↔External Receipt 对账；
- 记录 RPO / RTO。

不能只恢复数据库然后看页面能打开。

# 20. 每模块 Final Gate

每个 HRxx 只有同时满足以下条件才允许：

```text
HRxx READY FOR ACCEPTANCE
```

最低标准：
- 本模块 P0/P1 blocking=0；
- 00 全局合同符合；
- MySQL migration/test 全绿；
- Tenant/IDOR/Permission 负向全绿；
- 核心业务 E2E 全绿；
- Event/Provider contract 全绿；
- Legacy mapping/cutover 状态明确；
- Excel/async/file/audit 按本模块适用范围闭环；
- 可观测性与失败恢复存在；
- 文档行为与真实代码一致。

# 21. 系统级最终商业化 Gate

只有以下全部绿色：

```text
GLOBAL ARCHITECTURE CONTRACT READY
DOCUMENT CONTRACT BASELINE READY
HR01 READY FOR ACCEPTANCE
...
HR18 READY FOR ACCEPTANCE
CROSS-DOMAIN E2E GREEN
MYSQL FULL REGRESSION GREEN
SECURITY / TENANT ISOLATION GREEN
BACKUP / RESTORE DRILL GREEN
LEGACY FORMAL WRITES = 0
P0 = 0
P1 BLOCKING = 0
```

才允许：

```text
SYSTEM READY FOR PRODUCTION ACCEPTANCE
```

任何 red / pending / expected / 被跳过的强制 Gate 都不算通过。

# 22. 第一所学校试运行前

1. 建真实 tenant。
2. 配组织/岗位/权限/制度。
3. 导入授权的真实或脱敏数据。
4. 至少真实验证 HR03/07/11/15/16 五个高风险域。
5. 人事、学院、普通教师、工资员、领导账号分别测试。
6. PC + HR17 高频移动查看。
7. 模拟 Provider failure。
8. 跑一次测试工资月结。
9. 跑一次 HR18 正式报送 Package（测试环境）。
10. 跑一次退休/离校 Case。
11. 恢复一次备份。
12. 现场问题进入缺陷 Case，禁止直接手改数据库。

# 23. 实现完成后再生成的交付文档

当前**不要继续手工提前写**，等真实代码稳定后生成：

- `API_REFERENCE`：从 OpenAPI 生成。
- `GLOBAL_EVENT_REGISTRY`：从 event schemas 生成。
- `PERMISSION_MATRIX.xlsx`：从角色/权限配置生成。
- `DATA_DICTIONARY.xlsx`：从最终 schema + metadata 生成。
- `INTEGRATION_CATALOG`：真实第三方确定后生成。
- `OPERATIONS_RUNBOOK`：部署拓扑冻结后生成。
- `UAT_ACCEPTANCE_CASES.xlsx`：从 E2E 测试生成。
- `RELEASE_CHECKLIST`：上线前生成。
- `CUSTOMER_DELIVERY_INDEX`：第一所学校交付时生成。
- 开源依赖与 License 清单：从真实 lockfile/SBOM 生成。

原则：

> **能从代码自动生成的，就不要再人工维护第二份事实源。**

# 24. 最终客户交付包建议

实现完成后，成熟商业交付包应包含：

1. HR01–HR18 功能目录。
2. 系统架构与部署拓扑。
3. 权限角色矩阵。
4. 数据字典。
5. API / Integration Registry。
6. 安全设计说明。
7. 数据备份恢复方案。
8. 运维手册。
9. 人事管理员手册。
10. 普通教职工使用手册。
11. 数据迁移方案与迁移报告。
12. UAT 验收报告。
13. 性能测试报告。
14. 租户隔离/越权测试报告。
15. 版本发布说明。
16. 第三方组件与开源许可清单。

# 25. 编码 AI 总控指令

```text
你现在负责跃科高校人事管理与教师发展系统 HR01–HR18 的正式施工。

文档优先级：
1. 00_高校人事系统全局架构与旧系统接管合同.md
2. 99_高校人事系统18模块施工总控与最终验收总册.md
3. HR01-HR18_总一致性与遗漏复审报告_终极版.md
4. 当前施工 HRxx 对应《施工总册_终极版》
5. 其他 HRxx 总册仅用于跨域契约参考

第一阶段必须完成 PATCH-00→PATCH-12。
DOCUMENT CONTRACT BASELINE READY 前，不允许大规模 Authority 施工。

全局强制：
- MySQL-only；
- Canonical API=/api/v1/hr；
- tenant fail-closed；
- no cross-domain direct formal ORM write；
- no silent legacy fallback；
- effective-dated；
- FINAL/EFFECTIVE 用 revision/correction/revocation；
- Outbox/Inbox；
- idempotency；
- real async jobs；
- Excel staging/validation/error workbook；
- file/field security；
- HR18 owns MetricDefinition；
- canonical Event/Permission Registry；
- MySQL/security/E2E/restore 全绿；
- 不使用 git add -A；
- 未经明确授权不 push、不 merge main、不生产部署。

每个模块只有 blocking=0 才输出：
HRxx READY FOR ACCEPTANCE

全系统只有全部 Gate 绿色才输出：
SYSTEM READY FOR PRODUCTION ACCEPTANCE
```

# 26. 最终结论

现在不建议继续增加大量设计文档。

**当前完整设计集应该收口为：**

```text
00  全局架构与 Horilla 接管合同
01–18  各业务域施工总册
复审报告  18 册总一致性与遗漏复审
99  18 模块施工总控与最终验收
```

这已经足够进入正式施工。

后续 API、Event、Permission、Data Dictionary、UAT、Runbook 等，应随着真实代码落地后自动生成或基于真实实现编写，避免“文档比代码更早成为过期第二真相”。
