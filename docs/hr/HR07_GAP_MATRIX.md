# HR07 GAP Matrix（S0 基线复审 · 对照总册终极版）

> 依据：《00_全局架构合同》（§28.2 权限 / §28.3 事件 / §110 Payroll.Contract 接管 / §117-119 公共域）、
> 《07_HR07_合同与聘用_施工总册_终极版》五个三级模块 + #135 S0 清单。
> 核对对象：`renshi/` 真实代码（payroll + employee + base + horilla_documents + horilla_audit + notifications +
> hr_control_center + hr_structure + hr_staff + hr_onboarding + horilla_auth + horilla_views + horilla_api）。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`

---

## 0. 顶层裁决

| 层面 | 裁决 | 证据 / 说明 |
|---|---|---|
| `payroll.models.models.Contract` | **REWRITE + DEPRECATE** | 载荷薪资/考勤配置/单一 active 语义；HR07 重建 HrAgreement 体系，旧表仅 projection（00 §110） |
| `payroll.views.views.contract_*`（create/update/status/delete/bulk） | **REDIRECT_TO_HR07 / READONLY** | 新签走 HR07 signing case；已签署不可 edit；delete 仅 DRAFT 无引用 |
| `payroll.scheduler.expire_contract` | **REPLACE** | 用 `date.today()` 静默改状态违反 HR07 §16；由 `AgreementLifecycleScheduler` 幂等接管 |
| `payroll.signals.employeeworkinformation_pre_save` 自动建 Contract | **DECOUPLE/移除** | 隐式创建正式合同违反 Authority 纪律；HR05 Activation 通过 `ContractSigningTaskRequested` 显式进入 HR07 |
| `employee.EmployeeWorkInformation.contract_end_date` | **READONLY/LEGACY** | 快照字段，非合同权威；HR07 不写入 |
| `employee.methods.create_contracts_in_thread`（Excel 导入自动建 Contract） | **REPLACE** | 历史导入改走 HR07 Excel 流程（template→staging→validate→confirm→async），禁止 Excel 直接写 Contract |
| `horilla_documents.Document` | **ADAPT** | 做安全 Document Provider 基础；HR07 的签署件/附件走 private storage + hash + ticket（00 §117） |
| `horilla_audit` | **ADAPT** | 补 `HrAgreementAuditEvent` + `SensitiveAgreementAccessLog`（HR07 §80）；历史审计保留 |
| `notifications` | **ADAPT** | 事件驱动模板版本化 + 去重（HR07 §42）；现有 notify 只作兼容 |
| 电子签 | **NEW（V1 仅 OFFLINE + Adapter 契约）** | 无真实 provider；OFFLINE 生产可用，Mock 仅测试（HR07 §92） |

---

## 1. 硬门核对（H0 / A0 / HR02 / HR03 / HR05 / HR06 / HR15 / HR16）

### H0 基础
| 硬门项 | 现状 | 差距 |
|---|---|---|
| INSTALLED_APPS 注册新 app | `hr_contracts` **未创建** | HR07-S2 注册 `hr_contracts` 并 wire apps.py |
| 迁移可执行 | payroll 有 0001-0004；hr_staff 0011；hr_onboarding 0006 | HR07 全部 MySQL 落地；SQLite 仅轻量单测（00 §26） |
| Shell/git/CI | 本机沙箱无 shell，**无法跑 migrate/test/git** | 提交由用户在 IDE 执行；测试脚本按阶段交付 |

### A0 多学校 fail-closed
| 硬门项 | 现状 | 差距 |
|---|---|---|
| 租户可信上下文 | `CompanyMiddleware` + `hr_control_center.context.resolve_tenant_from_request` + `build_hr_context` ✅ | HR07 复用 `HrRequestContext`，新增 `Hr07RequestContext`（authority_mode） |
| 无 tenant 上下文 fail-closed | 已有 `TENANT_CONTEXT_REQUIRED` 范式 | HR07 所有写 API + selector 强制；禁止 `isnull=True` 全校兜底 |
| 后台 Job 租户 | hr_onboarding 有 outbox dispatcher 范式 | HR07 的 lifecycle/risk/outbox job 显式 tenant + system actor（00 §59） |
| scope 统一 | `HrScope` SCHOOL/COLLEGE/DEPARTMENT/ASSIGNED ✅ | HR07 合同管理员 SCHOOL；学院 HR 本学院 scope（HR07 §67） |

### HR02 边界（00 §90）
- `HrOrganization/HrPosition/HrPostCatalog` 已可用；HR07 合同签约快照 `signing_context_snapshot` 保存签署时组织/岗位，**不复制当前组织为长期权威**（HR07 §70）。

### HR03 边界（00 §93 / HR07 §70）——最高优先
| 能力 | 真实状态 | 判定 |
|---|---|---|
| `HrEmploymentRelationship`（[effective_from,effective_to)） | hr_staff S3 已建（relationship_type/status/version） | ✅ **引用，不重建** |
| `HrStaffAssignment`（PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT） | 已建 + `AssignmentService.switch_primary` | ✅ |
| `EffectiveDatedQueryService.relationships_as_of / primary_assignment_as_of / status_as_of` | 已实现 | ✅ HR07 全部 as-of 查询走此服务 |
| `EmploymentService.start_relationship / end_relationship` | 已实现 | HR07 不调用 start；end 由 HR16 流程触发（HR07 不代做 HR16） |
| HR03 事件 | `StaffActivated` 等已冻结 | HR07 只消费 HR03 引用事实；`EmploymentRelationship` 变更只影响 HR07 impact 评估，不自动改合同文本 |

### HR05 边界（00 §92 / HR07 §71）
| 项 | 现状 | 差距 |
|---|---|---|
| Activation → `ContractSigningTaskRequested` | **未实现**（HR05 尚无 contract task 概念） | HR07-S8 与 HR05 对齐契约；HR07 返回 `NOT_REQUIRED/DRAFT/UNDER_APPROVAL/WAITING_SIGNATURE/SIGNED/ACTIVE`；是否 BLOCKS_ACTIVATION 由学校 OnboardingPolicy 决定 |
| `payroll.signals` 自动建 Contract | 存在且自动 `contract_status="active"` | 必须停用/改为只建 legacy projection 占位，不建权威 |

### HR06 边界（00 §94 / HR07 §72）
- HR06 `PersonnelChangeEffective` → HR07 `ContractImpactEvaluator` 输出 `NO_IMPACT/REVIEW_REQUIRED/AMENDMENT_REQUIRED/NEW_AGREEMENT_REQUIRED`；**HR06 不自动改合同文本**。S0 时 HR06 尚未交付 `PersonnelChangeEffective` 消费端点 → HR07-S8 以契约 + idempotent inbox 预留。

### HR15 边界（00 §110 / HR07 §75）
| 项 | 现状 | 差距 |
|---|---|---|
| `payroll.models.Contract.wage` | 薪资权威（`compute_salary_on_period`/`payroll_calculation` 直读） | **DECOUPLE**：HR07 只保留 `compensation_reference`/条款引用，不读金额做统计（用户硬门） |
| `Contract.save` 回写 `EmployeeWorkInformation.basic_salary` | 存在（wage→int→save） | **移除/冻结**；HR15 负责实际薪酬档案（S9 解耦门） |
| `Payslip.contract_wage` | 月结快照字段 | 保留为历史快照；新数据由 HR15 provider 提供 |

### HR16 边界（00 §103 / HR07 §76）
- HR16 `ExitEffective/RetirementEffective` → HR07 终止/解除合同事件；HR07 不搬离校流程。S0 时 HR16 未交付 → HR07-S8 消费端以契约预留，`Completion Gate`（all required agreements ended）为 HR16 侧校验项。

---

## 2. 现存 Legacy 入口清点（逐项裁决）

### 2.1 创建/编辑 `payroll.Contract` 的入口
| 入口 | 文件:行 | 权限 | 裁决 |
|---|---|---|---|
| `contract_create` | payroll/views/views.py:78 | payroll.add_contract | **REDIRECT_TO_HR07**（新签走 signing case） |
| `contract_update` | payroll/views/views.py:114 | payroll.change_contract | **REDIRECT_TO_HR07 / 禁改 active** |
| `contract_status_update` | payroll/views/views.py:164 | payroll.change_contract | **READONLY → HR07 状态机** |
| `bulk_contract_status_update` | payroll/views/views.py:217 | payroll.change_contract | **READONLY → HR07 状态机** |
| `update_contract_filing_status` | payroll/views/views.py:255 | payroll.change_contract | **HR15 归属** |
| `contract_delete` / `contract_bulk_delete` | payroll/views/views.py:280/1400 | payroll.delete_contract | **只允许 DRAFT 无引用；正式合同禁删**（HR07 §58） |
| `employeeworkinformation_pre_save` | payroll/signals.py:12 | —（signal） | **移除/冻结**（隐式建权威合同） |
| `create_contracts_in_thread` | employee/methods/methods.py:730 | —（导入） | **REPLACE**（HR07 Excel 导入） |
| `contract_ending` | payroll/views/views.py:900 | — | READONLY 到期查询，HR07 风险中心接管 |
| CBV `ContractsList/ContractsNav/ContractsDetailView` | payroll/cbv/contracts.py | payroll.view_contract | READONLY 兼容视图 → HR07 台账 |

### 2.2 读取 `Contract.wage` 的入口（Payroll 解耦门清单）
| 入口 | 文件:行 | 归属 |
|---|---|---|
| `payroll_calculation`（basic_pay 来源） | payroll/views/component_views.py:294 | HR15 |
| `compute_salary_on_period` / hourly/daily/monthly | payroll/methods/methods.py:597-628 | HR15 |
| `salary_computation`（L270/304/499/541） | payroll/methods/methods.py | HR15 |
| allowance 页面 basic_pay | payroll/cbv/allowance_deduction.py:125-129 | HR15 |
| payslip 生成 contract_wage | payroll/cbv/payslip.py:348、views.py:937/1072 | HR15 |
| 模板展示 `contract.wage` | payroll/templates/contract/*.html | 展示层 |
| 旧表单 initial `$("#id_wage")` | payroll/templates/common/form*.html | 展示层 |

### 2.3 Contract save 副作用
| 副作用 | 文件 | 处理 |
|---|---|---|
| 自动补 department/position/role/shift/work_type | models.py:441-458 | 改存 `signing_context_snapshot`，不做权威 |
| end_date<today → status=expired | models.py:459-460 | **违反 HR07 §16**，由 Lifecycle Service 接管 |
| 单 active/单 draft 约束 | models.py:461-485 | 改由 `AgreementFamily.overlap_policy/max_active` 参数化（HR07 §8） |
| wage → basic_salary 回写 | models.py:487-503 | **移除**（HR15） |
| unique_together(employee,start,end) | models.py:510 | legacy 仅存 |

### 2.4 到期 scheduler
| 项 | 现状 | 处理 |
|---|---|---|
| `expire_contract()` | payroll/scheduler.py:20，每 4h `update(status="expired")` | **REPLACE**：`AgreementLifecycleScheduler`（SIGNED_WAITING_EFFECTIVE→ACTIVE；review_date→REVIEW_DUE；end→EXPIRED/RISK；signature expiry）每项幂等 |

---

## 3. 权限裁决（00 §28.2 Canonical Registry）

- 新 HR07 权限统一 **`hr.contract.<resource>.<action>`**（00 §28.2：HR07 → `hr.contract`）；通过 `HrContractPermissionMeta`（managed=False）注册到 DB。
- 旧 `payroll.add_contract/change_contract/...` 保留给 legacy projection/兼容页，**不再授权新入口**。
- HR07 §68 权限矩阵映射：
  - `hr.contract.agreement.view / create / edit_draft / submit / approve / generate / issue / activate`
  - `hr.contract.renewal.review / renewal.decide`
  - `hr.contract.amendment.create / termination.create / termination.approve / correction.create / void`
  - `hr.contract.template.view / template.manage / rule.manage`
  - `hr.contract.document.view / document.download / sensitive_download`
  - `hr.contract.risk.view / risk.manage / export`

## 4. 事件裁决（00 §28.3 Global Event Registry）

- 新正式跨域事件（HR07 §91）命名采用 00 §28.3 风格：`ContractEffective / ContractTerminated`（已冻结），其余 HR07 内部事件：
  `AgreementDraftCreated / AgreementApproved / AgreementGenerated / AgreementSignatureRequested / AgreementSigned / AgreementActivated / AgreementReviewDue / AgreementRenewalStarted / AgreementRenewed / AgreementAmended / AgreementVoided / AgreementCorrectionApplied / AgreementRiskOpened / AgreementRiskResolved`。
- 00 §28.3 冻结的 `ContractEffective / ContractTerminated` 作为跨 HR03/HR05/HR06/HR15/HR16 的对外事件；HR07 内部走 `HrContractOutboxEvent`（同事务 outbox）。

## 5. API 路径裁决（00 §28.1 vs HR07 §81）

- 已交付模块实际前缀均为 `/api/hr/v1/<domain>`（hr03=staff、hr05=onboarding）；HR07 总册 §81 亦为 `/api/hr/v1/contracts/*`。
- **HR07 采用 `/api/hr/v1/contracts/*`**（与已交付 HR03/HR05 一致、可被真实前端消费）；00 §28.1 的 `/api/v1/hr` 属后续全系统统一 Consolidation，HR07 在 API envelope（apiVersion/schemaVersion/requestId）+ 错误信封 + additive-only 上严格对齐 00 §29/§30，并在本矩阵记录该偏差待总控复核。
- 新契约测试以 `/api/hr/v1/contracts/...` 为 Authority。

## 6. 前端中文化裁决

- 所有 HR07 模板/JS 可见文案中文：标题/导航/按钮/表头/表单/空态/错误态/状态徽标（ACTIVE→履行中、EXPIRING→即将到期、SIGNED_WAITING_EFFECTIVE→已签待生效 等）。
- 优先 Django i18n（`{% trans %}/{% blocktranslate %}`）；数据库枚举值不改，只改展示层（badge label 映射在 display_labels/templatetags）。
- 台账 JSON：字段 camelCase；中文用 `xxxLabel` 成对；错误 message 中文（HR07 §12 JSON 规范）。

## 7. S0 结论

```text
HR07 基线复审通过（业务未改动）。
关键事实：
- payroll.Contract 是薪资+考勤+合同三合一旧表，必须解耦；
- 到期状态由日期静默推断，必须状态机接管；
- 已交付 HR03 权威可直接引用（HrEmploymentRelationship/Assignment/EffectiveDatedQueryService）；
- 无 hr_contracts app、无模板/规则/签署/事件/风险任何概念 → 全部 NEW；
- 电子签无真实 provider → V1 OFFLINE + Adapter 契约；
- Shell 不可用：本机无法跑 migrate/test/git，测试与提交由用户在 IDE 执行。
```
