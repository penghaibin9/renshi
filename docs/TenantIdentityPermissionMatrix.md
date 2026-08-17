# TenantIdentityPermissionMatrix

> 来源：00_高校人事系统全局架构与Horilla接管合同.md §8–§10, §28.2, §36–§41
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09

---

## 1. Canonical Permission Registry（§28.2 冻结）

| 模块 | Canonical Domain Prefix | 当前代码实际 | 状况 |
|---|---|---|---|
| HR01 | `hr.dashboard` | `hr01.*` | 统一使用现状 `hr01.*` |
| HR02 | `hr.organization` | `hr02.*` | 统一使用现状 `hr02.*` |
| HR03 | `hr.staff` | `hr03.*` | 统一使用现状 `hr03.*` |
| HR04 | `hr.recruitment` | `hr04.*` | ✅ 已实现 |
| HR05 | `hr.onboarding` | `hr05.*` | ✅ 已实现（16 权限码 + 0006 migration） |
| HR06 | `hr.change` | `hr06.*` | 待开窗 |
| HR07 | `hr.contract` | `hr07.*` | 待开窗 |
| HR08 | `hr.external` | `hr08.*` | ✅ 已实现（19 权限码） |
| HR09 | `hr.qualification` | `hr09.*` | 待开窗 |
| HR10 | `hr.development` | `hr10.*` | 待开窗 |
| HR11 | `hr.time` | `hr11.*` | 待开窗 |
| HR12 | `hr.assessment` | `hr12.*` | 待开窗 |
| HR13 | `hr.title` | `hr13.*` | 待开窗 |
| HR14 | `hr.appointment` | `hr14.*` | 待开窗 |
| HR15 | `hr.payroll` | `hr15.*` | 待开窗 |
| HR16 | `hr.exit` | `hr16.*` | 待开窗 |
| HR17 | `hr.self` | `hr17.*` | 待开窗 |
| HR18 | `hr.data` | `hr18.*` | 待开窗 |

> **总控裁决（2026-08-09）**：保持 `hrNN.*` 统一现状，不迁移到 `hr.<domain>.*`。
> 代码已 100% 使用 `/api/hr/v1` + `hr04.*/hr08.*` 风格，系统内自洽。
> 新开窗模块继续使用 `hrNN.*` 风格，禁止混用。

---

## 2. 权限格式规则

```text
hrNN.<resource>.<action>

示例：
- hr04.recruitment_plan.view
- hr04.application.manage
- hr05.onboarding_case.view
- hr08.profile.view
- hr08.hiring_case.approve
```

SELF 权限与平台权限单独 namespace：
- `self.*` — 本人操作权限
- `platform.*` — 平台运营权限（默认无学校人事/工资/档案权限）

---

## 3. Data Scope 统一矩阵

| Scope | 含义 | 适用场景 |
|---|---|---|
| `SCHOOL` | 全校范围 | HR 管理员、校领导 |
| `COLLEGE` | 学院范围 | 学院秘书、学院负责人 |
| `DEPARTMENT` | 部门范围 | 教研室/科室负责人 |
| `ASSIGNED` | 分配给本人的范围 | 评委/导师 |
| `SELF` | 仅本人 | 普通教职工 |

规则：
- KPI、列表、导出、drilldown 使用同一个 `ResolvedScope`
- 有页面权限 ≠ 有字段权限
- Scope 变更后角色/组织缓存及时失效
- 员工调离后不能继续缓存旧学院权限

---

## 4. Tenant Root 总合同

| 规则 | 实现要求 | 当前状态 |
|---|---|---|
| 所有学校级事实显式 `tenant_id` | 每张 Authority 表必含 `tenant_id` 或可从聚合根解析 | ✅ HR03-05/08/11 已实现 |
| request/job/event/provider 携带 tenant context | context 中间件/Job 参数/Event envelope | ✅ HR03 context.py 已实现 |
| 无法确定 tenant → fail-closed (403) | 禁止默认第一学校、`all`、前端过滤 | ✅ 各窗口已遵守 |
| 前端传 `tenant_id` 不是授权依据 | 后端从 session/token 解析 tenant | ✅ `context.py` |
| list/search/autocomplete/export/dashboard/files/jobs/events 同 scope | 同一 `ResolvedScope` 贯穿所有操作 | ⚠️ 待全系统验证 |
| 跨 tenant FK 写入失败 | DB 约束 + 应用校验 | ✅ 各窗口 model 有 tenant FK |
| Job/Event consumer 显式 tenant context | 不能依赖当前 HTTP request | ⚠️ 部分 Job 待加固 |
| 平台运营默认无学校人事/工资/档案权限 | Break-glass 要 reason/timebox/audit | 待实现 |

---

## 5. Person / User / Staff 分层

```text
Person          — 自然人身份（身份证/指纹去重，可多段聘用/返聘/多角色）
User            — 系统账号（IAM 管 session/MFA/group/access）
Staff           — 教职工（Person + EmploymentRelationship）
EmploymentRelationship — 一段聘用关系 [from, to)
Assignment      — 具体任职段（PRIMARY/CONCURRENT/TEMPORARY/SECONDMENT）
ExternalEngagement — 外聘/兼职/产业教授
```

禁止规则：
- 禁止单一 `Employee` 表吞掉全生命周期
- 同一自然人可以退休后返聘、多段聘用、多 Engagement、多角色

---

## 6. SoD（职权分离）

以下操作必须支持 maker-checker：

| 操作 | 审批要求 |
|---|---|
| 合同解除 | maker + checker |
| 职称 final | maker + checker |
| 聘任 final | maker + checker |
| 工资调整/final/payment | maker + checker |
| 离校 effect | maker + checker |
| 正式上报 | maker + checker |

---

## 7. 数据分级与字段加密

| 分级 | 内容 | 处理 |
|---|---|---|
| `PUBLIC` | 公开信息 | 无需保护 |
| `INTERNAL` | 内部信息 | 登录可读 |
| `PERSONAL` | 个人信息 | scope 控制 |
| `SENSITIVE_PERSONAL` | 身份证/联系电话/家庭信息 | 加密/mask/reveal permission/key rotation |
| `HIGHLY_RESTRICTED` | 工资/银行卡/医疗/处分/匿名评议 | 加密或 tokenization；禁入日志；CSS 隐藏不是权限 |

---

## 8. IAM 边界

- IAM 管：账号/session/MFA/group/access
- HR 管：Person/Employment/Staff
- provision/deprovision 用 Provider receipt + reconciliation
- 授权必须走 IAM；HR 不自建登录会话

---

*由 00_高校人事系统全局架构与Horilla接管合同.md §160 自动生成。*
