# HR12 Legacy PMS Write Inventory — S1.8 输出

> 清点时间: 2026-08-09
> 扫描来源: `renshi/pms/urls.py` (141 条路由)

## Write 端点分类

| 路由组 | Write 端点数 | 典型操作 | cutover 策略 |
|---|---|---|---|
| **Feedback** | 27 路由中约 12 write | create/update/delete/archive/bulk-create/bulk-archive/bulk-delete/status | FREEZE 后 REDIRECT |
| **Anonymous Feedback** | 6 路由中约 4 write | add/edit/archive/delete | FREEZE 后 REDIRECT |
| **Objective** | 22 路由中约 8 write | create/template-create/update/add-assignees/delete/archive/bulk-archive/bulk-delete | FREEZE 后 REDIRECT |
| **Employee Objective** | 12 路由中约 6 write | create/update/archive/delete/status change/kr-current-value-update | FREEZE 后 REDIRECT |
| **Key Result** | 14 路由中约 6 write | create/update/delete/archive/creation/remove | FREEZE 后 REDIRECT |
| **Period** | 9 路由中约 4 write | create/update/delete/change | FREEZE 后 REDIRECT |
| **Question Template** | 12 路由中约 6 write | create/template-create/update/delete question/template update/delete | FREEZE 后 REDIRECT |
| **Meetings** | 17 路由中约 6 write | create/update/delete/archive/add-response/answer-post | FREEZE 后 REDIRECT |
| **Bonus Point** | 15 路由中约 8 write | create/update/delete setting & employee bonus point | **DEPRECATE** |
| **Settings** | 12 路由中约 0 write | (read-only templates/periods lists) | READONLY |
| **Dashboard** | 11 路由中约 0 write | (read-only API) | DEPRECATE (ranking) / REPLACE |
| **合计** | **~60 write endpoints** | — | — |

## cutover 阶段策略

```text
LEGACY_ACTIVE           → 当前状态（141 路由全量可写）
  ↓
S10: FREEZE_LEGACY_FORMAL_WRITES
  - /pms/* 所有 POST/PUT/PATCH/DELETE → 405 Method Not Allowed
  - GET 保留（compat/readonly）
  - BonusPoint 相关 → 永久 410 Gone（不迁移）
  ↓
S12: LEGACY_READONLY_PROJECTION
  - GET 路由 → compat redirect → /hr/assessments/*
  - deprecation metric 计数
  ↓
S13+: POST_CUTOVER_CLEANUP
  - 移除 compat redirect
  - 删除旧 /pms/* 路由注册（仅保留数据库表用于审计）
```

## 高风险 Write 端点（必须优先 freeze）

1. `feedback-bulk-*` — 批量操作 Feedback，影响面大
2. `objective-bulk-*` — 批量操作 Objective
3. `key-result-current-value-update/` — 员工可自行修改 KR 当前值
4. `change-employee-objective-status/` — 员工/主管可修改目标状态
5. `bonus-point-setting/*` — 积分规则 CRUD（跨 module 信号副作用）
6. `employee-bonus-point/*` — 积分增减（连 employee→payroll 链）
