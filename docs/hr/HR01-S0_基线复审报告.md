# HR01-S0 基线复审报告（依据真实仓库核对）

> 复审时间：2026-08-08
> 复审对象：`penghaibin9/renshi` Horilla HRMS 2.0 fork
> 本地路径：`F:\高校人事系统\renshi`
> 基线提交：`ca7928f chore: remove one-time Horilla bootstrap workflow`（main 分支，工作树干净）
> 依据文档：《01_HR01_人事工作台_施工总册_终极版》第 35 节 HR01-S0

---

## 1. 结论先行

- 总册对 `employee/dashboard.py` 的 **P0-01 / P0-02 / P0-03** 与 **P1-01 / P1-03 / P1-05** 判断**与真实代码完全吻合**，裁决成立。
- **A0 现状比总册假设的要好**：仓库已经存在 `HorillaCompanyManager` + `CompanyMiddleware` + `COMPANY_SCOPED_PERMISSIONS`，不是从零开始。但**未满足总册 A0 完成标准**（缺 fail-closed、school timezone、聚合/钻取同一范围合同、后台任务 scope 等）。
- `TIME_ZONE` 默认 `Asia/Kolkata`，印证总册第 18 节「学校时区」硬合同的必要性。
- **上游测试红灯无法在本地完整复现**：`employee/tests.py` 为空文件；完整回归需要 Docker/Postgres/Redis 环境，当前未搭建，不能宣称测试全绿。
- **决策：HR01 按总册进入 S1；`LegacyDataMapping.md` 本报告同步物化初版。**

---

## 2. 实际文件清单（S0 要求读取的文件，全部存在）

| 总册点名文件 | 仓库实际路径 | 存在 | 备注 |
|---|---|---|---|
| `employee/dashboard.py` | `renshi/employee/dashboard.py` | ✅ | 9 个 JSON API + 1 个 render view，全部 `@login_required` |
| `employee/models.py` | `renshi/employee/models.py` | ✅ | Employee / EmployeeTag / EmployeeWorkInformation / EmployeeBankDetails / Policy / DisciplinaryAction 等 |
| `employee/urls.py` | `renshi/employee/urls.py` | ✅ | `dashboard/` + `dashboard/api/*` 共 9 个路由 |
| `employee/sidebar.py` | `renshi/employee/sidebar.py` | ✅ | “My Dashboard” → `ess-dashboard`（ESS 语义，确认） |
| `employee/templates/employee/dashboard.html` | `renshi/employee/templates/employee/dashboard.html` | ✅ | CDN 加载 ApexCharts；约 430 行内联 CSS + 内联 JS |
| `report/` | `renshi/report/` | ✅ | views/ 下有 employee/attendance/leave/payroll/recruitment 等报表 |
| `horilla_widgets/` | `renshi/horilla_widgets/` | ✅ | 仅 select / file / multi_select 小部件，无 HR 组件体系 |
| `horilla_audit/` | `renshi/horilla_audit/` | ✅ | HorillaAuditLog / get_diff；`EmployeeWorkInformation.history` 已挂审计 |
| `notifications/` | `renshi/notifications/` | ✅ | 第三方 django-notifications + `notifications.urls` |
| `base/models.py` | `renshi/base/models.py` | ✅ | Company / Department / JobPosition / JobRole / WorkType / EmployeeType / EmployeeShift |
| `base/horilla_company_manager.py` | `renshi/base/horilla_company_manager.py` | ✅ | HorillaCompanyManager（多公司过滤 + is_active 默认过滤） |

S0 额外核实（总册未点名但影响施工）：

| 文件 | 作用 |
|---|---|
| `base/middleware.py` | `CompanyMiddleware`：session `selected_company` → `set_selected_company()` |
| `horilla/horilla_middlewares.py` | `current_company_id` ContextVar + `get/set_selected_company` |
| `base/auth_backends.py` | `CompanyScopedBackend` + `get_allowed_company_ids` 等 |
| `base/dashboard.py` | “现代 dashboard”（`/dashboard/`），与 ESS dashboard 混叠 |
| `base/urls.py` | `dashboard/`、`ess/` + ESS JSON API |
| `horilla/urls.py` | 主路由：`employee/`、`horilla-widget/`、`inbox/notifications/`、health/ready 等 |
| `horilla/settings/base.py` | INSTALLED_APPS、MIDDLEWARE、TIME_ZONE、CACHES、COMPANY_SCOPED_PERMISSIONS |
| `employee/tests.py` | 空文件（无任何测试） |

---

## 3. 真实模型关系（关键）

### `Employee`（`employee/models.py`）

```
Employee
├── badge_id                      CharField(50)  唯一(badge_id, 非空时)  ← HR03 Staff Number 候选
├── employee_user_id              OneToOne → HorillaUser
├── employee_first_name/last_name CharField      ← 中文姓名拼接语义需重定义
├── email / phone                 unique / 敏感  ← HR03 Person Contact
├── dob / gender                  DateField / choices
├── qualification                 CharField(50)  单字符串 ← DEFER，不是结构化资格
├── experience                    IntegerField   粗粒度 ← DEFER
├── is_active                     BooleanField   当前激活投影 ← PROJECT（不是历史真值）
├── additional_info               JSONField
└── objects = HorillaCompanyManager(related_company_field="employee_work_info__company_id")
```

- `Meta.unique_together = (employee_first_name, employee_last_name, email)`；`badge_id` 有 UniqueConstraint。
- `save()` 会自动 `full_clean()`、自动创建 `HorillaUser`（email 为用户名、phone 为初始密码）、自动 `get_or_create(EmployeeWorkInformation)`、归档时若有业务关联会自动回弹 `is_active=True`（P1-07 潜在：归档逻辑耦合）。
- 拥有自定义权限 `change_ownprofile` / `view_ownprofile`。

### `EmployeeWorkInformation`（当前 snapshot，不具 effective-dated 历史能力——与总册第 30 节描述一致）

```
EmployeeWorkInformation  (OneToOne → Employee, related_name="employee_work_info")
├── department_id        FK → Department (PROTECT)
├── job_position_id      FK → JobPosition (PROTECT)
├── job_role_id          FK → JobRole (PROTECT)
├── reporting_manager_id FK → Employee
├── shift_id             FK → EmployeeShift (DO_NOTHING)
├── work_type_id         FK → WorkType (PROTECT)
├── employee_type_id     FK → EmployeeType (PROTECT)
├── company_id           FK → Company (PROTECT)
├── location             CharField
├── email / mobile       工作联系方式
├── date_joining         DateField      ← HR03 EmploymentRelation.effective_from 候选
├── contract_end_date    DateField      ← HR07 合同投影（COMPAT/DEFER）
├── basic_salary / salary_hour  IntegerField  ← HR15 薪酬，高敏感
├── additional_info / experience
└── history = HorillaAuditLog(...)     ← 有审计变更历史（可用于变更追溯，但非 effective-dated 任职事实）
```

### `base` 组织字典

```
Company        → HorillaModel，company/hq/address/country/state/city/zip/icon/date_format/time_format；objects=Manager()
Department     → company_id M2M→Company；HorillaCompanyManager()
JobPosition    → department_id FK + company_id M2M；HorillaCompanyManager("department_id__company_id")
JobRole        → job_position_id FK + company_id M2M
WorkType       → company_id M2M
EmployeeType   → company_id M2M
EmployeeShift  → company_id M2M
```

### A0 关键机制（已存在，需强化）

- `CompanyMiddleware`（`base/middleware.py`）：
  - 已登录用户 → 从 session 读 `selected_company` → clamp 到 allowed company ids → `set_selected_company(company_id)` → 写回 session。
  - 无会话时回退到用户默认公司；`request.allowed_company_ids / assigned_company_ids / all_my_company_ids / write_company_id` 挂在 request 上。
  - `_clamp_to_allowed` 已存在（越权切换会被限制）。
- `HorillaCompanyManager.get_queryset()`：
  - `company == "all"` 时非 superuser 限制到 `all_my_company_ids`；superuser 全量。
  - 单一公司时 `filter(company_id=X | company_id__isnull=True)`（**注意：`isnull=True` 是共享字典，但对学校业务对象意味着未绑定组织的教职工仍可见——需 HR01 按 fail-closed 重新裁决**）。
  - `all()` 默认过滤 `is_active`（employee 模型尊重 `request.GET.is_active`）。
- `COMPANY_SCOPED_PERMISSIONS = True`（settings）：权限按公司 group assignment 解析。

**A0 缺口（对照总册 1.1 A0 清单）：**

| A0 要求 | 现状 |
|---|---|
| 当前学校 tenant 上下文解析 | ✅ 有（Company + ContextVar） |
| 无学校上下文 fail-closed | ⚠️ `isnull=True` 兜底 + “all” 路径；对 HR01 需硬 fail-closed |
| 用户只能选有 membership 的学校 | ✅ `_clamp_to_allowed` 已存在 |
| 学校 A 数据不能通过钻取看到 B | ⚠️ Manager 层有过滤，但 dashboard 直接 query 未统一走 scope 合同 |
| 后台任务明确 school scope | ❌ 未发现通用机制 |
| 聚合与明细同一数据范围合同 | ❌ 不存在 |
| 学校时区进 HrRequestContext | ❌ 不存在；全局 `TIME_ZONE=Asia/Kolkata` |

---

## 4. 当前 dashboard API（碎片化确认 P1-01）

`employee/urls.py` 下 dashboard 相关路由（9 个）：

```
dashboard/                     → employee_dashboard_view          (render)
dashboard/api/kpi/             → employee_kpi_data
dashboard/api/departments/     → employee_by_department
dashboard/api/gender/          → employee_by_gender
dashboard/api/type/            → employee_by_type
dashboard/api/position/        → employee_by_job_position
dashboard/api/joining-trend/   → employee_joining_trend
dashboard/api/headcount/       → employee_headcount_trend
dashboard/api/recent/          → employee_recent_list
dashboard/api/birthdays/       → employee_upcoming_birthdays
```

另外 `base/urls.py` 还挂了一组“现代 dashboard”：

```
dashboard/       → base.dashboard.main_dashboard_view   (现代 dashboard，ApexCharts + 大量 except pass)
ess/             → ess_dashboard.ess_dashboard           (ESS 自助)
ess/api/kpi|payslips|objectives|upcoming → ESS JSON API
```

`base/dashboard.py` 中同样存在：`except Exception: pass` 大量出现、`date.today()` 直接用服务器日期、`is_active=True` 反推 headcount、按 `-id` 排 recent——与 P0-02/P0-03/P1-04 一致。

---

## 5. 与总册的冲突 / 差异（裁决核对）

| # | 总册说法 | 真实代码 | 裁决 |
|---|---|---|---|
| 1 | P0-01 仅 login_required | ✅ `@login_required`，无 HR01 独立权限码 | REWRITE 权限层成立 |
| 2 | P0-02 headcount 用 is_active + date_joining<=month_end | ✅ 完全一致（`employee_headcount_trend`） | 禁止作为历史事实成立 |
| 3 | P0-03 except pass 吞异常 | ✅ KPI/生日/leave 多处 | fail-open 禁止成立 |
| 4 | P1-01 前端 9 个碎片 API | ✅ 9 个路由 + base dashboard 更多 | bootstrap 聚合成立 |
| 5 | P1-02 模板内联 CSS 过重 | ✅ ~430 行 `<style>` + 内联 style | Design System 成立 |
| 6 | P1-03 CDN 加载 ApexCharts | ✅ `<script src="https://cdn.jsdelivr.net/npm/apexcharts">` | 本地化成立 |
| 7 | P1-04 recent 用 -id | ✅ `order_by("-id")` | 改为 date_joining 口径成立 |
| 8 | P1-05 生日占核心面积 | ✅ 右侧 sidebar 有 🎂 Upcoming Birthdays | 从 HR01 移除成立 |
| 9 | A0 尚未封板 | ⚠️ 已有 CompanyMiddleware + CompanyScopedBackend + HorillaCompanyManager，但缺 fail-closed/timezone/scope 合同 | **强化而非新建** |
| 10 | TIME_ZONE 需学校化 | ✅ 全局 `Asia/Kolkata` | HrRequestContext.school_timezone 必须落地 |
| 11 | “My Dashboard” 是 ESS 语义 | ✅ sidebar “My Dashboard”→ ess-dashboard | HR01 独立菜单，不混叠 |
| 12 | 总册假设模板 1000 行内联 CSS | ⚠️ 实际约 430 行 + 内联 JS 约 190 行 | 不影响裁决，仍须拆组件 |
| 13 | Horilla `Employee` 归档会回弹 active | 真实存在（`save()` 中 `get_archive_condition()`） | 新增风险：归档/离职语义与高校“离退”口径冲突，写进 S3 风险 |

无「总册与代码冲突到必须改合同」的项；主要差异是 A0 现状比总册假设乐观。

---

## 6. 上游测试红灯（诚实声明）

- `employee/tests.py`：空模板文件（只有 `from django.test import TestCase` + 注释），**无任何 employee 测试**。
- 仓库内测试分布在各 app（base/recruitment/leave/payroll/pms 等 34 个 `tests.py`），但完整跑通需要：
  - PostgreSQL / Redis（Docker Compose 提供 `REDIS_URL`）；
  - 真实 SMTP/外部服务可能被 mock。
- **当前本地未搭建 Docker 环境，无法给出“全绿”结论。** 必须先复现 H0 基线（Docker 可重复构建 + system check + health/ready）后再谈测试基线。
- 按总册要求：区分“上游欠账”（Horilla 原有测试缺失/失败）与“跃科新增回归”（HR01 自己的测试），不得用跳过测试伪造全绿。

---

## 7. A0 状态总结

**A0 = 部分存在，未封板。**

已有：
- Company 多公司隔离（Manager 层 + Middleware + ScopedBackend + `COMPANY_SCOPED_PERMISSIONS`）。

缺口（HR01 生产封板前必须补齐）：
1. HR01 API fail-closed：无学校上下文 → `403 TENANT_CONTEXT_REQUIRED`，不做 `isnull=True` 全校兜底；
2. `HrRequestContext.school_timezone`（学校时区进统计上下文）；
3. 聚合指标与 drilldown 的**同一 ResolvedHrScope 合同**；
4. 后台任务 school scope；
5. 学校 A 数据经 HR01 导出/钻取/图表不可见学校 B 的负向测试。

---

## 8. 可直接复用 / 需保留 / 需重写

| 对象 | 处理 |
|---|---|
| `HorillaCompanyManager` + `get_selected_company()` | **保留**，作为 HR01 底层范围过滤基础，但 HR01 走自身 scope 合同 |
| `Company`（base） | ADAPT：作为学校租户根/兼容投影 |
| `Department/JobPosition/JobRole/EmployeeType` | COMPAT：HR02/HR03 前当前组织投影 |
| `horilla_audit` | ADAPT：高敏感查看/导出补审计 |
| `notifications` | ADAPT：预警通知通道 |
| `report` | REVIEW：可借筛选/导出基础，不作为 HR01 指标事实 |
| `base/dashboard.py` 现代 dashboard | 保持 ESS/首页语义，与 HR01 分离 |
| `employee/dashboard.py` | **REWRITE**（数据逻辑迁入 selector/service/provider） |
| `employee/templates/employee/dashboard.html` | **REWRITE UI**（拆公共组件） |
| ApexCharts | KEEP + HARDEN（本地固定版本 + 公共 wrapper） |
