# HR03 GAP MATRIX（S0 基线复审 · 现状→目标差距矩阵）

> 依据：《03_HR03_教职工主档_施工总册_终极版》六层真相 + 当前 `renshi` 仓库真实代码。
> 覆盖：六个三级模块 + 横向硬合同（有效日期/A0/敏感字段/审计/导入导出/事件）。
> 严重度：P0=阻塞封板；P1=必须 S1-S12 内完成；P2=可后置但必须登记。

---

## 1. 横向硬合同缺口（决定 S1-S3 架构）

| ID | 能力 | 现状（代码事实） | 目标 | 缺口 | 严重度 | 归属阶段 |
|---|---|---|---|---|---|---|
| G-H-01 | Person/Staff 分层 | `Employee` 单表承载身份+当前工作字段，`save()` 自动建 User/WorkInfo | HrPerson → HrStaffMaster → Relationship → Assignment 四层 | 全缺（REWRITE） | P0 | S2 |
| G-H-02 | 多 EmploymentRelationship | 无；`EmployeeWorkInformation` OneToOne | 一人多关系（返聘/外聘/再次入职） | 全缺 | P0 | S3 |
| G-H-03 | effective-dated 任职 | 无；work_info 当前快照，调岗直接 UPDATE | `[effective_from,effective_to)` 半开区间 + as-of 查询服务 | 全缺 | P0 | S3 |
| G-H-04 | 主岗/兼岗 | 单 department/job_position 字段 | PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT；同关系同日唯一 PRIMARY | 全缺 | P0 | S3 |
| G-H-05 | A0 tenant 硬门 | `CompanyMiddleware`+`HorillaCompanyManager`（公司过滤）；`hr_control_center` 有 `build_hr_context` fail-closed | HR03 权威表自带 tenant_id；FK 同 tenant 校验；无 context fail-closed | 部分具备（可复用 ContextVar 方案），权威表未建 | P0 | S1/S2 |
| G-H-06 | HR02 稳定 ID 依赖 | **S0 复核更新**：`hr_structure` 已注册 INSTALLED_APPS、已有 0001_initial 迁移、`HrOrganization/HrPosition/HrPostCatalog/HrLegacyObjectLink` 模型与 as-of 查询（`hr_structure.selectors.effective`）就绪 | organization/position 直接 FK HR02 模型；legacy 经 HrLegacyObjectLink 映射；未映射数据用 `LEGACY_CURRENT_SNAPSHOT` 预览 | **基本闭合**（数据映射待 S11） | P1 | S3/S11 |
| G-H-07 | 敏感字段四级 + reveal 审计 | 无分级；`Employee.email/phone` 直接进列表；身份证无模型 | PUBLIC/RESTRICTED/SENSITIVE/HIGH_SENSITIVE；身份证 ciphertext+fingerprint+masked_display；reveal=purpose+审计+60s 遮罩 | 全缺 | P0 | S2/S8/S9 |
| G-H-08 | 人员状态机 | `is_active` Boolean；归档可回弹 | 状态由关系/任职段推导；离职/退休不 DELETE | 全缺 | P0 | S3/S9 |
| G-H-09 | 账号与身份解耦 | `Employee.employee_user_id` OneToOne + save 自动建 User | `HrAccountLink` 1:0..n；authority save 禁建账号 | 缺 | P1 | S2 |
| G-H-10 | 统一 as-of 查询服务 | 各模块自拼日期条件 | `EffectiveDatedQueryService` 唯一入口 | 缺 | P0 | S3 |
| G-H-11 | 并发控制 | 无 version/乐观锁；PRIMARY 无约束 | version bigint + 409 VERSION_CONFLICT；PRIMARY 唯一约束/事务锁 | 缺 | P1 | S3 |
| G-H-12 | 正式业务审计 | `HorillaAuditLog`（simple-history，依赖 thread，宽 try/except） | `HrStaffAuditEvent` + `HrSensitiveAccessLog` | 缺（KEEP+NEW） | P1 | S2/S8/S9 |
| G-H-13 | 事件/outbox | 无 | `StaffCreated/AssignmentChanged/...` outbox | 缺 | P1 | S10 |
| G-H-14 | 数据质量中心 | 无 | 异常类型清单+页面 | 缺 | P2 | S11 |

## 2. HR03-01 教职工名册

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-01-01 | 统一人员搜索入口 | `employee-view-new/`（Form 模板）+ `employees-list/`（cbv） | `/hr/staff` + `/api/hr/v1/staff` | 新路由+权威 Provider | P1 | S4 |
| G-01-02 | 服务端安全筛选 | `EmployeeFilter`（含 is_active、permission filter） | QuerySpec（受控字段，不接任意 ORM path） | 重写 | P1 | S4 |
| G-01-03 | Saved View | 无 | filters_json 受控 schema + 重新权限裁剪 | 缺 | P2 | S4 |
| G-01-04 | 批量动作边界 | 现有批量 archive/update 直接改 | 仅材料请求/核对/导出/标签；禁批量改组织岗位 | 约束缺 | P1 | S4 |
| G-01-05 | 高敏字段不进列表 API | `email/phone/dob` 在 legacy 列表可见 | 默认只 PUBLIC_HR 字段；RESTRICTED 按权限 | 缺 | P0 | S4 |
| G-01-06 | 大导出异步 | `work_info_export` 同步 pandas | 10000+ 行异步 + 字段权限 + ticket | 缺 | P1 | S4/S8 |
| G-01-07 | 首屏统计 | dashboard 多处 count(is_active) | 3~5 个可信数字，HR03 Provider | 重写 | P1 | S4 |

## 3. HR03-02 教职工主档

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-02-01 | Profile 权威页 | `profile-new`（cbv employee_profile）基于 Employee | `/hr/staff/{staffId}` + bootstrap API | 重写 | P1 | S5 |
| G-02-02 | as-of 历史查看 | 无 | Header 切历史值 + 只读模式 + 组织名 as-of 解析 | 缺 | P0 | S5 |
| G-02-03 | 编辑策略 | work tab 直接改 department/position | 基本/联系可改；组织岗位状态走 HR06/13/14/16 | 重写 | P1 | S5 |
| G-02-04 | 风险/待办摘要 | `document` 到期提醒部分 | 合同到期/材料待核验/更正待审等 | 需新 Provider | P2 | S5 |
| G-02-05 | N+1 预算 | 无 | profile ≤15~25 SQL | 新代码约束 | P1 | S5 |

## 4. HR03-03 任职与身份履历

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-03-01 | 任职 timeline/表格 | 无 | relationship+assignment 双视图 | 全缺 | P0 | S6 |
| G-03-02 | 新建任职来源约束 | 无 | 仅 HR05/06/14/16/MIGRATION_VERIFIED/AUTHORIZED_CORRECTION | 全缺 | P0 | S6 |
| G-03-03 | 兼岗语义 | 无 | assignment_type 四值 | 全缺 | P0 | S6 |
| G-03-04 | 历史不可改 | legacy 无历史 | 历史 segment 只读；更正走 CorrectionCase | 全缺 | P0 | S6/S9 |
| G-03-05 | HR02 组织 as-of 名称 | 无 | 组织名历史解析（依赖 HR02） | 缺 | P1 | S6 |

## 5. HR03-04 教育资格履历

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-04-01 | 教育经历多条 | `Employee.qualification` 单字符串 | HrEducationExperience 多条 + 校验 | 重写 | P1 | S7 |
| G-04-02 | 学历/学位分离 | 无 | HrEducationExperience + HrDegreeRecord | 缺 | P1 | S7 |
| G-04-03 | 工作经历 | `experience` 数字 | HrWorkExperience 结构化 | 重写 | P1 | S7 |
| G-04-04 | 资格证书 | 无 | HrCredential/HrCertificate + evidence 绑定 | 缺 | P1 | S7 |
| G-04-05 | 人才荣誉 | 无 | HrTalentHonor | 缺 | P2 | S7 |
| G-04-06 | 数据质量状态 | 无 | COMPLETE/REQUIRED_MISSING/CONFLICT/UNVERIFIED/EXPIRED | 缺 | P1 | S7 |

## 6. HR03-05 人事材料档案

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-05-01 | 材料元数据+版本 | `Document`（单文件，无版本链） | HrStaffMaterial + HrStaffMaterialVersion（SHA-256/版本/作废） | 重写 | P1 | S8 |
| G-05-02 | 敏感文件访问控制 | `view-file`（直接 media 文件响应） | download-ticket 短时效 + tenant/scope/sensitivity/purpose/audit | **P0 安全缺口** | P0 | S8 |
| G-05-03 | 裸 URL 暴露 | `Document.document.url`（`/media/...` 可猜） | 禁止裸 URL；受控票据 | 缺 | P0 | S8 |
| G-05-04 | 材料分类字典 | `title` 自由文本 | category_code 字典（IDENTITY/EDUCATION/…） | 缺 | P1 | S8 |
| G-05-05 | 材料请求 | `DocumentRequest`（M2M employee） | HrMaterialRequest（target/category/due/status） | 适配 | P2 | S8 |
| G-05-06 | 水印 | 无 | 动态水印不修改原文件 | 缺 | P2 | S8 |

## 7. HR03-06 信息更正与历史

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-06-01 | FieldGovernancePolicy | 无 | field edit_mode/required_permission/approval_policy | 缺 | P0 | S9 |
| G-06-02 | Correction 状态机 | 无 | DRAFT→SUBMITTED→…→APPLIED/REJECTED | 缺 | P0 | S9 |
| G-06-03 | before/after + 影响分析 | `get_diff`（simple-history） | HrCorrectionItem + impact 分级 | 缺 | P1 | S9 |
| G-06-04 | BUSINESS_PROCESS_ONLY 防绕过 | 无 | 更正不可改 BP 字段 | 缺 | P0 | S9 |
| G-06-05 | 历史 diff 页面 | 无 | 修改前/后 + 证据 + 审批记录 | 缺 | P2 | S9 |

## 8. Legacy 退出合同

| ID | 能力 | 现状 | 目标 | 缺口 | 严重度 | 阶段 |
|---|---|---|---|---|---|---|
| G-L-01 | 权威/legacy 模式标识 | provider `authority_mode`（LEGACY_ONLY）已有框架 | HR03_AUTHORITY 后禁 fallback（contract test） | 缺 HR03 provider 实体 | P1 | S11 |
| G-L-02 | Authority→Legacy 单向投影 | 无 | HrLegacyEmployeeProjectionService + reconciliation | 缺 | P1 | S11 |
| G-L-03 | email 全局唯一解除 | `unique=True` + 建 user 逻辑 | 逐行改造 legacy Employee 投影 + 账号解耦 | 缺 | P1 | S11 |
| G-L-04 | 导入 staging 化 | 同步逐行+批量混合 | HrImportJob/Row/Issue 异步提交 | 缺 | P1 | S11 |

---

## 结论

- **P0 = 13 项**，全部集中在：Person/Staff/Relationship/Assignment 四层骨架、effective-dated、A0 表级 tenant、敏感字段与文件访问控制、状态机、更正治理。
- **P1 = 27 项**，覆盖六个三级模块的 REWRITE。
- **P2 = 9 项**，可后置但已登记（Saved View/水印/数据质量页面等）。
- **HR02 依赖门**当前未闭合（`hr_structure` 未入 INSTALLED_APPS、无迁移）——S3 起所有组织/岗位引用按"权威位可空 + legacy 映射列"施工，S11 回填。
