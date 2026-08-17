# HR08_GAP_MATRIX（初版 · HR08-S0 基线复审输出）

> 权威事实源：`docs/08_HR08_兼职外聘教师_施工总册_终极版.md`
> 依据：`renshi` 仓库真实代码核对（2026-08-09）
> 状态：`DRAFT_V1`

## 1. 结论先行

HR08 是 REWRITE。现状 Horilla 没有任何 External Workforce/Contingent 领域，外聘事实被塞进 `Employee + EmployeeType + WorkInformation + payroll.Contract`。所有外聘能力缺口集中在：**身份/类别权威、Engagement 生命周期、审批/合规、教学与服务任务、工作量验证、续聘/退出、访问生命周期、教务/IAM 集成、Legacy 隔离**。

## 2. 逐项差距矩阵

| # | 领域 | HR08 要求（总册章节） | 现状（真实代码） | 缺口 | 优先级 | 解决阶段 |
|---|---|---|---|---|---|---|
| G01 | 自然人身份根 | 复用 HR03 `HrPerson`，tenant-private（§6.1/§6.2） | HR03 已交付 `hr_staff.HrPerson/PersonIdentityService`（tenant_id 列 + fingerprint 去重） | ✅ 无缺口 | - | S2 已满足闸门 |
| G02 | 外聘教师档案 | `HrExternalTeacherProfile`（§16/§24） | 无 | 全缺：profile/external_teacher_no/来源单位/能力标签/资格/受聘历史 | P0 | S2/S3 |
| G03 | 外聘类别配置 | `HrExternalCategory` + Title/Engagement 分离（§5/§18） | `base.EmployeeType` 仅 CharField 字典；60+ 处引用且语义=文本 | 类别策略（伦理/资格/协议/访问/结算/任期）全缺 | P0 | S1 |
| G04 | Engagement/Work Order | `HrExternalEngagement` 状态机（§19/§20） | `WorkInformation.contract_end_date` 单字段；`payroll.Contract` 无聘期状态机 | 全缺：起止/review_at/状态机/agreement gate/多重叠规则 | P0 | S2/S5 |
| G05 | 多学院并行 | 一人多 Engagement/多 Assignment（§21/§22/§23） | OneToOne WorkInformation 只支持单部门 | 全缺 | P0 | S2 |
| G06 | 聘用审批 | `HrExternalHiringCase` + 资格审查（§32-43） | 无 | 全缺：需求/候选/资格/伦理/冲突/审批/协议闸门/激活 | P0 | S2/S5 |
| G07 | 师德/伦理审查 | `HrExternalEthicsReview`（§36） | 无 | 全缺（合规流程只做框架，不推断政治倾向） | P0 | S2/S5 |
| G08 | 利益冲突声明 | `HrExternalConflictDeclaration`（§37） | 无 | 全缺 | P0 | S2/S5 |
| G09 | 重复聘用检查 | 系统提示重叠/重复（§38/§39/§40） | 无；重复人靠 legacy 姓名 | 全缺：active engagement 重叠/workload cap/正式员工兼任/退休返聘 | P0 | S2/S5 |
| G10 | 产业教授/技能大师 | 专项 Profile/任务/成果（§27-31） | 无 | 全缺：产业经历/成果/工作室/贡献模型 | P1 | S4 |
| G11 | 教学与服务任务 | `HrExternalServiceTask` + Task Matrix（§44-56） | 无 | 全缺：任务计划/来源域引用/接受/证据/验收 | P0 | S2/S7 |
| G12 | 工作量可验证 | `HrExternalWorkloadRecord` + 验证流（§51/§52） | 无 | 全缺：source/quantity/验证/结算依据（HR15 边界） | P0 | S7 |
| G13 | 续聘/退出 | Review/决策/Exit/权限回收（§58-70） | 无；legacy 只有 `end_date < today → expired` | 全缺：review/决策/新 Engagement/ExitCase/回收闭环 | P0 | S8 |
| G14 | 访问授权 | `HrExternalAccessGrant` + IAM 集成（§66-68/§94-99） | `Employee.save()` 自动建账号；无 scope grant | 全缺：scoped grants/expires_at/聚合/回收 | P0 | S2/S6 |
| G15 | 教务教师身份 | `HrExternalAcademicIdentity`（§96/§97） | **无任何教务集成**（grep academic/教务 无业务模块） | 全缺：external teacher identity 同步 | P0 | S6 |
| G16 | 结算边界 | SettlementBasis → HR15（§53/§100） | `payroll.Contract.wage` + 写回 basic_salary（应归 HR15） | HR08 不存工资；输出 verified workload + settlement basis | P0 | S7 |
| G17 | 风险引擎 | RiskType/Severity/Take Action（§106-108） | HR01 alert_service 仅基于 Employee 完整性 | 全缺：agreement 缺失/过期/权限超期/任务超期/工作量未验 | P1 | S7/S8 |
| G18 | Legacy 投影 | worker_kind=EXTERNAL 标记（§6.3/§112/§113） | `HrStaffMaster` 无 worker_kind 字段；HR11/HR15/leave/attendance 均以 `Employee.is_active`/Contract 判定 | HR08 侧建 worker_kind 标记 + 投影隔离，不改 HR03 | P0 | S9 |
| G19 | 重复人迁移 | identity evidence + 人工 review（§117） | HR03 PersonIdentityService 已有 HARD/LIKELY match | HR08 引入 identity match endpoint（§26） | P1 | S3 |
| G20 | API 版本化/错误信封 | §81-87 | hr_staff/hr_control_center 已有 api/base.py 模式 | HR08 复用模式新建 | P1 | S1 |
| G21 | 权限/数据范围 | §88/§89/§90 | hr_staff.permissions 有 require_* 模式 | HR08 新 scope 类型（ENGAGEMENT/ASSIGNED_TASKS/SELF） | P0 | S1 |
| G22 | 审计/敏感访问 | `HrExternalAuditEvent`/`SensitiveExternalAccessLog`（§109） | horilla_audit 仅技术历史；hr_staff 已有 audit_service 模式 | HR08 新建正式审计 | P1 | S2 |
| G23 | Outbox 事件 | §103 | hr_staff 尚无 outbox 实现 | HR08 建立生命周期事件信封（复用 00 §15 格式） | P1 | S2/S5 |
| G24 | Excel 迁移 | §110 | Horilla employee import 同步逐行 save | HR08 重建 staging 异步导入 | P2 | S3/S9 |
| G25 | 约束/索引/并发 | §118/§119/§121 | hr_staff 有 constraints/索引先例 | HR08 全量落库 | P0 | S2 |

## 3. HR03 → HR08 Provider/Event 契约（00 §95，闸门）

| 方向 | 契约 | 状态 |
|---|---|---|
| HR08 → HR03（读） | `HrPersonProvider`：by id / by identity fingerprint / create person via `PersonIdentityService.create_person_with_identity` | ✅ HR03 已交付服务可用 |
| HR08 → HR03（读） | `StaffMasterProvider`：外聘目录投影需要 Staff ID 时 `StaffMasterService.create_staff(source=受控)` | ✅ 服务可用；**仅投影**，不进入正式 EmploymentRelationship |
| HR08 → HR03（事件） | `StaffActivated` 等消费（仅当外聘转正式时走 HR04/05/03 正式链） | 设计占位（S6 后按 HR04/05 交付情况落地） |
| HR08 → HR07（读/占位） | `AgreementProvider`：解析 `agreement_id/agreement_status` | ⚠️ HR07 未交付 → Provider 契约占位（S2 落地占位实现） |
| HR08 → 教务（双向） | `AcademicProvider/Event`：ExternalEngagementActivated → teacher identity；课程任务 → HR08 reference | ⚠️ 无教务系统 → 契约+UNAVAILABLE（S6） |
| HR08 → IAM（写） | `AccessProvisioningProvider`：scoped grants/回收，异步 provisioning + reconciliation | ⚠️ 无 IAM → 契约+UNAVAILABLE（S6） |
| HR08 → HR15（写） | `SettlementBasisReady` 事件输出 verified workload | ⚠️ HR15 未交付 → 契约占位（S7） |

## 4. P0 阻断项（S1/S2 必须处理）
1. 无外聘类别权威（EmployeeType 文本无法表达策略）——S1 `HrExternalCategory`；
2. 无 Engagement 生命周期——S2 模型 + 状态机；
3. 无访问生命周期——S2 `HrExternalAccessGrant` + S6 provisioning；
4. 无教务/IAM 集成——S6 Provider 契约（不 mock 冒充）；
5. Legacy `Employee` 副作用入口（自动建账号/wage 写回/全量 payslip）——S9 隔离，Authority 切换前不得让外聘投影落入正式 Payroll/Leave/Attendance。
