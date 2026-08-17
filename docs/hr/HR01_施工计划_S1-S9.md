# HR01 施工计划（S1～S9）

> 依据：《HR01 施工总册（终极版）》第 35 节 + S0 基线复审
> 原则：一个阶段一个可验证提交；全程 Draft PR；S3 前硬门已过（LegacyDataMapping 已物化 DRAFT_V1）
> 新增 app：`hr_control_center`（跨域聚合，不属于任何单个业务域）

---

## 依赖关系图

```
S1 公共 UI 底座 ──────────────┐
S2 后端骨架 + Authority Router ─┤
                              ▼
S3 人事总览 (HR01-01)  ← 硬门：LegacyDataMapping + maxStaleSeconds + API version
                              │
        ┌─────────────────────┼──────────────────────┐
        ▼                     ▼                      ▼
S4 我的待办 (HR01-02)   S5 人事预警 (HR01-03)   S6 队伍结构 (HR01-04)
        │                     │                      │
        └─────────────────────┼──────────────────────┘
                              ▼
S7 快捷办理 (HR01-05)  ← 依赖 S2 registry + 各域 provider
                              ▼
S8 Horilla 兼容迁移与 Authority Cutover
                              ▼
S9 全量验收
```

- S3 依赖 S1（UI 组件）+ S2（骨架/contract/provider router）+ LegacyDataMapping。
- S4/S5/S6 依赖 S2 骨架；S5 依赖 alert 规则配置；S6 依赖 workforce provider。
- S7 依赖 S2 的 quick action registry + 各业务域 `scope_validator`。
- S8 是横切阶段，任何阶段完成后都可逐步叠 Compatibility。

---

## 各阶段任务拆解

### HR01-S1 公共 UI 底座（预计修改：新增 `templates/hr/`、`static/hr/`；不动业务代码）

任务：
1. design tokens（CSS 变量：Primary/Text/Surface/Canvas/Border/Success/Warning/Danger/Info，间距 4-8-12-16-20-24-32-40，圆角 8/12/16，字体层级）。
2. 核心组件：`HrPageHeader`、`HrContextBar`、`HrMetricCard`、`HrMetricStrip`、`HrSectionCard`、`HrRiskBadge`、`HrFreshnessBadge`、`HrStateView`（loading/empty/partial/stale/unavailable/permission_denied/error）、`HrChartCard`、`HrQuickAction`、`HrDataQualityBanner`、`HrTable`、`HrPagination`、`HrSkeleton`、`HrTimeline`、`HrFilterBar`、`HrStatusTabs`。
3. ApexCharts 本地化：固定版本下载到 `static/hr/vendor/apexcharts/`，`HrChart` wrapper 封装（dark/light token、table fallback、tooltip 口径）。
4. 页面模板薄化示范页（总览骨架，不接业务数字）。
5. 1280/1366/1440/1920 响应式 + `prefers-reduced-motion`。

验收：视觉验收红线全过；无 CDN 依赖；无 `transition: all`；无 1000 行内联 CSS 样板。

### HR01-S2 后端控制中心骨架 + Authority Router（预计新增 `hr_control_center/` 全套）

任务：
1. `HrRequestContext`（tenant/school、school_timezone、asOf、period、scope、requestSnapshotAt、authorityMode）。
2. `scope.py`：`ResolvedHrScope` + scope 解析（SCHOOL/COLLEGE/DEPARTMENT/ASSIGNED）+ scopeFingerprint。
3. `permissions.py`：HR01 权限码（`hr.dashboard.view` 等 11 个）+ 权限校验装饰器。
4. `services/metric_registry.py`：`MetricDefinition` + 注册表（含 cacheTtlSeconds/maxStaleSeconds/hardExpireSeconds/serveStaleOnError）。
5. `providers/base.py`：`ProviderResult`（status/data/reasonCode/...）+ authority provider router（LEGACY_ONLY/DUAL_READ_COMPARE/AUTHORITY_ONLY）+ `HrAuthorityCutover` 模型 + `LegacyEmployeeProvider`（LEGACY_ONLY 阶段）。
6. `services/overview_service.py` 等 service 编排；`selectors/`（只读、吃 context、返回 DTO）。
7. `api/`：统一 response envelope（apiVersion/schemaVersion/requestId/generatedAt）、error envelope、401/403/409/422/503 语义。
8. 缓存：cache key builder（tenant+scope+metric+asOf+period+definitionVersion+authorityMode）+ freshness evaluator + single-flight（Redis 可用时）。
9. 可观测性：结构化日志字段 + 慢查询 warning。
10. 测试：unit（registry/freshness/router/scope）。

验收：`hr.dashboard.view` 权限 + fail-closed；无 `date.today()` 直用；无 `except Exception: pass`。

### HR01-S3 人事总览 HR01-01（预计修改：`hr_control_center/` 增加 overview；`employee/urls.py` 加 redirect）

硬门复查：
- [ ] LegacyDataMapping 已评审（DRAFT_V1 已物化，S3 编码前确认 REVIEWED 升级路径）；
- [ ] legacy provider mode 可控；
- [ ] `MetricDefinition.maxStaleSeconds` 已实现；
- [ ] API root version contract 已实现。

任务：
1. `/hr/`、`/hr/overview` 路由 + `employee/dashboard/` 兼容 redirect（权限允许时）。
2. `GET /api/hr/v1/home/bootstrap`（首屏聚合：context + 6 KPI + todo summary + alert summary + quick actions + freshness，单请求）。
3. K01-K06 六个 KPI（在岗/专任/双师/本年新进/本年离退/待处理风险），每项带 status/asOf/period/scope/definitionVersion/dataBasis/freshness/drilldown。
4. lazy-load：`overview/metrics`、`headcount-trend`、`recent-changes`。
5. 人数变化趋势图 + 结构摘要图（仅 2 张图，其余移 HR01-04）。
6. 同屏一致性合同（tenantId/scopeFingerprint/asOf/period/schoolTimezone/requestSnapshotAt + consistency）。
7. 历史 headcount：无 HR03 权威事实时 `UNAVAILABLE`，禁止错误趋势。
8. 生日提醒移除（P1-05 落地）。

风险：
- Legacy snapshot 无法回答历史 → 趋势/结构必须显式 `UNAVAILABLE` 或“当前快照不可回溯”。
- `Employee.save()` 归档回弹 → 离退口径需业务确认（S0 新增风险）。

### HR01-S4 我的待办 HR01-02（预计修改：`hr_control_center/` 增加 todo；接 recruitment/onboarding 真实来源）

任务：
1. `HrTodoProvider` Protocol（provider_key/get_summary/list_todos）+ registry。
2. 至少接入可确认的真实来源：recruitment（招聘流程待办）、onboarding（入职待办）、employee（文档/请求待办，如 `document_request`、`dashboard_pending_approvals` 同源数据）。
3. `GET /api/hr/v1/home/todos/summary` + `GET /api/hr/v1/home/todos`（DB 分页，禁止前端分页）。
4. 排序：CRITICAL > 逾期 > dueAt > submittedAt。
5. TodoItem 标准合同；`batch_action_supported` 由业务域声明。
6. 不做 `POST /home/todos/{id}/approve`（审批回业务域）。
7. 待办数/超时用 school timezone。

验收：无假待办；provider 失败 → PARTIAL/ERROR，不 fake-zero。

### HR01-S5 人事预警 HR01-03（预计修改：`hr_control_center/` 增加 alert；新增 `HrAlertInstance` 模型迁移）

任务：
1. `HrAlertInstance` 模型（tenant/alert_key/source_domain/dedupe_key/title/severity/status/first_seen/last_seen/due_at/owner/payload/resolved）+ 迁移 + `UNIQUE(tenant, dedupe_key, OPEN)`。
2. 规则代码化 + 参数配置：contract.expire_90d、retirement.within_180d、workflow.overdue、staff.required_field_missing（仅接已有真实数据源的规则，不造假预警）。
3. 状态机 OPEN/ACKNOWLEDGED/SNOOZED/RESOLVED/EXPIRED；`POST alerts/{id}/acknowledge|snooze`（乐观锁 version + idempotency key + audit）。
4. 严重度 CRITICAL/HIGH/MEDIUM/LOW/INFO；风险按类型分 Tab + 详情面板。
5. dedupe（同一天同一合同不重复 30 条）。
6. school timezone 计算 due/逾期。

验收：无提醒风暴；数据型规则只对已有字段生效；ack 不等于业务已解决。

### HR01-S6 队伍结构 HR01-04（预计修改：`hr_control_center/` 增加 workforce）

任务：
1. `GET workforce/summary`、`distribution?dimension=`（白名单维度）、`trend?metric=&grain=`、`org-comparison`。
2. 基于可确认数据提供：人员类别（employee_type 映射字典）、当前组织（department）、当前岗位（job_position）、性别。
3. 学历/职称/双师无权威事实 → `UNAVAILABLE`（不得造假）。
4. 小样本隐私 `<5`（非管理员角色，阈值配置化）。
5. 图表规范：line/horizontal bar/stacked bar/table 为主，慎用 donut，禁 3D 饼图。
6. 结论卡（专任占比/年轻占比/高级职称占比等，从定义推导）。

风险：`employee_type` 自由文本 → 必须先建映射字典，否则类别指标不可解释。

### HR01-S7 快捷办理 HR01-05（预计修改：`hr_control_center/` 增加 quick_actions）

任务：
1. `QuickAction` registry（key/label/required_permissions/required_module/route_name/icon/priority/audiences/allowed_scope_types/scope_validator/feature_flag/availability_provider）。
2. `GET /api/hr/v1/home/quick-actions` 服务端过滤（tenant+permission+scope+module+authority+flag+availability），前端只消费 catalog。
3. 首屏最多 6 个；`/hr/actions` 作为“更多办理”。
4. 无 dead link；disabled 必须有 reasonCode（如 CONTEXT_REQUIRED）。
5. 安全测试：COLLEGE 看不到 school-only action；改 scope 参数不能越权；权限回收后立即消失。

### HR01-S8 Horilla 兼容迁移与 Authority Cutover（预计修改：`employee/sidebar.py`、`employee/urls.py`、`horilla/urls.py`）

任务：
1. `/employee/dashboard/` redirect（权限允许时 → `/hr/overview`）；旧 template 下线但不粗暴删除。
2. sidebar 语义整理：新增 HR01 一级入口（人事工作台）；“My Dashboard” 保持 ESS 语义。
3. `HrAuthorityCutover` 按 tenant/domain 切换；HR02/HR03 ready 后先 `DUAL_READ_COMPARE` + 对账报告（在岗/学院/人员类别/组织映射/重复工号/跨租户差异）。
4. 切换硬门全过 → `AUTHORITY_ONLY`；legacy cache 失效；legacy fallback 负向测试。
5. 违规 legacy 调用监控（`hr_home_legacy_provider_call_total > 0` 告警）。

### HR01-S9 全量验收

覆盖总册第 33 节测试矩阵 + 第 34 节生产验收指标：
- tenant/scope 负向全绿；API version 合同；freshness；legacy cutover；unit/integration/performance/Playwright/visual/accessibility/security；Docker 构建；migration 一致；上游相关回归。

---

## 风险清单（汇总）

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| 1 | 上游测试无法本地复现（无 Docker/DB） | 不能宣称 H0 全绿 | S1 前先搭 Docker 复现 H0 基线 |
| 2 | `isnull=True` 兜底破坏 fail-closed | 跨校数据泄漏 | HR01 scope 层独立裁决，不做全校兜底 |
| 3 | `date.today()` 服务器日期当业务日期 | 统计日错误 | 全部走 school_timezone |
| 4 | `employee_type` 自由文本 | 类别指标不可解释 | 先建高校人员类别映射字典 |
| 5 | `Employee.save()` 归档回弹 | 离退口径失真 | 业务确认离退状态机，HR01 只读 |
| 6 | 历史 headcount 无法回溯 | 错误趋势 | `UNAVAILABLE` 而非伪历史 |
| 7 | 缓存串学校/串 scope | 数据泄漏 | cache key 带 tenant+scope+authorityMode；权限变更失效 |
| 8 | quick action 越权 | 权限绕过 | 服务端过滤 + 深链二次校验 |

---

## 预计修改/新增文件范围

```
新增：
  hr_control_center/
    __init__.py apps.py urls.py permissions.py scope.py context.py models.py
    api/{__init__,serializers,views}.py
    selectors/{__init__,overview,todo,alert,workforce}.py
    providers/{__init__,base,legacy_employee,recruitment,onboarding,contract,retirement}.py
    services/{__init__,metric_registry,overview_service,todo_service,alert_service,workforce_service,quick_action_service,cutover}.py
    tests/（unit + tenant isolation + scope + freshness + api + legacy/authority）
    migrations/
  templates/hr/components/*.html
  static/hr/css/hr-tokens.css
  static/hr/js/{core,components,pages}/...
  static/hr/vendor/apexcharts/（固定版本本地化）
  docs/hr/legacy/LegacyDataMapping.md ✅ 已物化
  docs/hr/HR01-S0_基线复审报告.md ✅ 已物化

修改：
  horilla/urls.py                 （挂 /hr/、/api/hr/v1/）
  horilla/settings/base.py        （INSTALLED_APPS 加 hr_control_center；school timezone 默认值可按学校配置）
  employee/urls.py                （dashboard/ redirect）
  employee/sidebar.py             （新增 HR01 一级入口）
  base/urls.py                    （如需要 context 提供 school timezone 支持）

复用（不修改或仅 ADAPT）：
  base/horilla_company_manager.py base/middleware.py base/auth_backends.py
  horilla_audit notifications report（review 后决定）
```

## 下一动作（用户授权后开始）

1. 搭建 Docker/H0 基线验证环境（`renshi` 仓库自带 compose）。
2. 创建 `hr_control_center` app 骨架（S2 先行，因为 S3+ 全部依赖）。
3. 建立 Feature/Draft 分支，按 S1 → S2 → S3 顺序逐个阶段提交。

> 阶段提交纪律：一个阶段一个可验证 commit；全程 Draft PR；未经明确授权不合并 main。
