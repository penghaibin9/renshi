# TargetDatabaseCompatibilityMatrix

> 来源：00_高校人事系统全局架构与Horilla接管合同.md §26（PATCH-00 冻结：MySQL-only）
> 生成指令：§160 Global-S0
> 生成日期：2026-08-09

---

## 1. 数据库目标（最高合同）

```text
Production / Development / Test / CI / Migration Acceptance = MySQL
```

- **禁止新增 PostgreSQL 专属 Authority 设计**：`daterange / btree_gist / GIST / ExclusionConstraint` 一律改为 MySQL 可落地实现
- 旧册中 PostgreSQL 描述仅作为**迁移识别知识**，不作为新 Authority 设计约束
- SQLite 只可做轻量单测，不是最终数据库验收

---

## 2. PostgreSQL → MySQL 迁移对照表

| PostgreSQL 特性 | MySQL 替代方案 | 落地方式 |
|---|---|---|
| `daterange` 类型 | `effective_from` + `effective_to` (DATETIME) | service validation + transaction lock |
| `ExclusionConstraint` 防止重叠 | 应用层 temporal overlap 校验 + DB `UNIQUE`/条件唯一 | `select_for_update` + 事务内校验 |
| `btree_gist` / `GIST` 索引 | 普通 B-tree 索引 + 条件索引 | `(tenant_id, effective_from, effective_to)` 复合索引 |
| `generate_series` | Python 生成或 calendar table | service 层处理 |
| `array_agg` | `GROUP_CONCAT` / JSON_ARRAYAGG | 按需选择 |
| `DISTINCT ON` | 子查询 + `ROW_NUMBER` | `SELECT ... FROM (SELECT *, ROW_NUMBER() OVER ...)` |
| `::jsonb` / JSONB 查询 | `JSON_EXTRACT` / `JSON_CONTAINS` | JSON 类型 + generated column |
| `ILIKE` | `LIKE` + `COLLATE utf8mb4_general_ci` | 统一 collation |
| Schema 隔离 | Database 隔离或 `tenant_id` 前缀 | PK `tenant_id` + FK cascade |

---

## 3. 已扫描的 PostgreSQL 残留（全部已清理）

| 位置 | 原内容 | 清理状态 |
|---|---|---|
| HR01 H0 | `PostgreSQL 迁移一致` | ✅ 已移除 |
| HR02 设计 | `daterange + ExclusionConstraint + btree_gist/GIST` | ✅ 已改为 MySQL 实现 |
| HR03 迁移 | `assignment overlap` 带 PG 假设 | ✅ 已改为 `effective_from/effective_to + service + lock + unique` |
| HR04 索引 | `PostgreSQL 根据真实查询计划优化` | ✅ 已改为 MySQL 索引设计 |
| 全代码 | PG 专属语法 | ✅ 无残留（仅 test 注释提及 PG 并发，非设计） |

---

## 4. MySQL 落地核查清单

| 检查项 | 要求 | 当前状态 |
|---|---|---|
| **金额/比例 使用 Decimal** | 禁止 Float 进入薪酬/额度计算 | ✅ |
| **JSON 字段** | 规则/快照可用 JSON；关键关系/金额/状态/索引字段不全部塞 JSON | ✅ |
| **UTF8MB4** | 统一字符集和 collation | 待 CI 验证 |
| **migration 双路径** | clean DB full migration + upgrade from previous baseline | ⚠️ 待 MySQL CI |
| **row locking** | `select_for_update` + atomic conditional update | ✅ HR03/05/08 已实现 |
| **deadlock retry** | 幂等重试 + 指数退避 | ⚠️ 部分实现 |
| **idempotency** | create staff/activation/signature/payroll finalize 必须 | ✅ HR03/04/05 已实现 |
| **大查询 EXPLAIN** | 全模块大查询需 MySQL EXPLAIN 验证 | ⚠️ 待 MySQL CI |
| **index regression** | 索引变更需验证实际查询计划 | ⚠️ 待 MySQL CI |
| **并发测试** | 20+ threads 抢最后岗位/编号/额度/finalize | ⚠️ SQLite 只能单写者，待 PostgreSQL CI → MySQL CI |
| **backup/restore drill** | MySQL + object storage + keys + migration state | ❌ 未执行 |
| **Decimal 序列化** | API 金额用字符串传输（防精度丢失） | ⚠️ 待验证 |

---

## 5. 索引名 30 字符限制修复记录（MySQL 违规）

Django 默认对 `models.Index(name="...")` 生成的索引名无长度限制，但 MySQL 限制索引名为 30 字符。

| 模块 | 违规数 | 修复方案 | 修复迁移 |
|---|---|---|---|
| `hr_external` | 39 个 | 全部改短名（`hex_*` 前缀） | `0014` |
| `hr_time` | 1 个 | `time_...` 改短 | `0011` |

---

## 6. Temporal Overlap 防重叠实现（MySQL 可落地）

替代 PostgreSQL `daterange + ExclusionConstraint`：

```python
# 1. 应用层校验
def validate_no_overlap(queryset, staff_id, effective_from, effective_to, exclude_id=None):
    overlapping = queryset.filter(
        staff_id=staff_id,
        effective_from__lt=effective_to or DATE_MAX,
        effective_to__gt=effective_from
    ).exclude(id=exclude_id)
    if overlapping.exists():
        raise OverlapError("时间区间重叠")

# 2. 事务内 select_for_update + unique/current constraint
with transaction.atomic():
    existing = Model.objects.select_for_update().filter(...)
    validate_no_overlap(existing, ...)
    Model.objects.create(...)

# 3. DB 条件唯一约束兜底
# ALTER TABLE ... ADD UNIQUE KEY uniq_active_primary (tenant_id, relationship_id, assignment_type) 
# WHERE effective_to IS NULL AND assignment_type = 'PRIMARY'
```

已在 HR03 `HrStaffAssignment` 实现：
- DB 条件唯一：`uniq_hr_assignment_open_primary_per_rel`
- `switch_primary` 使用 `select_for_update` 事务锁

---

## 7. 数据库目标验收 Gate

```text
MYSQL FULL REGRESSION GREEN
```

条件：
- migrations 从 clean DB 和 previous baseline 均通过
- 全量锁、并发、Decimal、JSON、索引 EXPLAIN 全绿
- rollback、restore 演练通过
- 测试库与生产数据库语义差异已列清

---

## 8. 当前阻塞

| 阻塞项 | 说明 | 影响模块 |
|---|---|---|
| MySQL CI 环境不可用 | 本机 Windows 无法 Docker | 全部 |
| SQLite 单写者限制 | 只能做轻量单测 | 全部 |
| PostgreSQL 并发测试未跑 | HR02/04 的 20 并发用例待生产 CI | HR02/04 |
| 备份恢复演练未执行 | DB + object storage + keys + migration state | 全部 |

---

*由 00_高校人事系统全局架构与Horilla接管合同.md §160 自动生成。*
