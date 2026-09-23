# HR05 S10-S12 验收封板清单（Authority 切换与封板）

> 依据：《05_HR05_入职管理_施工总册_终极版》§51-§61（验收）、§69（封板条件）、§44（Legacy 退出）、00 §56/§57/§158。
> 物化时间：2026-08-09 · 状态：`DRAFT_V1`（CI 环境恢复后逐项执行）
> 前置：S0-S9 已交付（S1-S7 业务主体 + S8 投影 + S9 迁移/对账）。

---

## 1. S10 全量验收清单

### 1.1 安全（05 §52 / 00 §60）—— 测试已落盘 `tests/test_security.py`

| 项 | 覆盖 |
|---|---|
| 跨 tenant 隔离 | A 校 case 在 B 校 selector/detail 不可见 ✅ |
| IDOR | 跨 tenant 猜 case/material id → None/404 ✅ |
| Portal token | 未知 token 不可枚举、明文不入库、失败锁定 ✅ |
| person_match | 禁止仅凭 email 判同人；LIKELY 需人工 ✅ |
| 高敏裁剪 | detail/list 不含 token/高敏明文 ✅ |

### 1.2 并发（05 §47）—— 测试已落盘 `tests/test_concurrency.py`

| 场景 | 覆盖 |
|---|---|
| 双 Activate 同一 case | 幂等返回原结果；不重复创建 ✅ |
| 同 HR04 来源并发建 case | `(tenant,source_type,source_id)` unique 兜底 ✅ |
| case_no 并发唯一 | tenant 内唯一约束 ✅ |
| Task 双完成 | `TASK_ALREADY_COMPLETED` ✅ |
| 转正双审批/双 fail | `PROBATION_ALREADY_FINALIZED` ✅ |

> 真实 20 线程并发需 PostgreSQL（SQLite 单写者限制）；已在台账标注 CI 后补跑。

### 1.3 性能（05 §51）—— 测试已落盘 `tests/test_performance.py`

| 项 | 覆盖 |
|---|---|
| case 列表 DB 分页 | WHERE→COUNT→ORDER→PAGE，无 Python 后过滤 ✅ |
| 详情字段预算 | 有限字段，不含高敏 ✅ |
| Portal 本人数据 | 仅本人 ✅ |

> 生产目标：case list p95<500ms / Activation Gate p95<800ms / Portal p95<800ms / Activation 核心事务<1.5s。CI 环境（PostgreSQL）跑真实容量。

### 1.4 API 契约（05 §61）

- apiVersion/schemaVersion/requestId/pagination/envelope/If-Match/idempotency/enum fallback —— `tests/test_contracts.py` ✅
- 新增路由（report/activation-gate/activate/materials/tasks/probations/portal）均统一 envelope。

### 1.5 E2E / 视口 / 无障碍（05 §58-§60）

- 20 步 E2E 场景：代码层已覆盖（handoff→portal→资料→材料→报到→Gate→激活→任务→转正）；Playwright 脚本待 CI 环境。
- 视口 1440/1280/768/375：模板为服务端渲染壳，Portal 375 mobile-first 已规划；浏览器验收待 CI。
- 无障碍：状态 badge 有文本、颜色非唯一状态（模板按 00 §48/§51 编写）。

---

## 2. S11 Authority 切换（05 §44 / 00 §56）—— 已实现

| 项 | 实现 |
|---|---|
| tenant 级三态 | `HrOnboardingAuthorityMode`（LEGACY_ONBOARDING_ONLY / DUAL_READ_COMPARE / HR05_AUTHORITY），迁移 0004 ✅ |
| 切换记录 | operator/old_mode/new_mode/reason/reconcile_report_id ✅ |
| 切换命令 | `python manage.py hr05_switch_authority --tenant 1 --mode HR05_AUTHORITY --reason ... --report ...` ✅ |
| 对账命令 | `python manage.py hr05_reconcile_legacy --tenant 1`（discrepancy 可见，禁止新空读旧）✅ |
| legacy 写关闭 | `legacy_write_disabled(tenant_id)` 供 Portal/路由层判定 ✅ |
| 禁止自动 fallback | HR05_AUTHORITY 后 Provider 故障不读旧系统（code 层无 fallback 分支）✅ |
| 回滚 runbook | 回切命令同 `hr05_switch_authority --mode LEGACY_ONBOARDING_ONLY`；正式回滚需 runbook + 审计 |

测试：`tests/test_s11.py` ✅

---

## 3. S12 封板条件核对（05 §69）

### 业务
- [x] 五个三级模块闭环（HR05-01/02/03/04/05 API+服务+模型全交付）
- [x] HR04→HR05→HR03 链路（handoff 幂等消费端 + Activation HR03 四步 + HR02 commit）
- [x] 放弃/延期/No-show/失败路径真实（decline 释放预占、delay 保留历史、ACTIVATION_FAILED）
- [ ] 真实角色旅程 Playwright（依赖 CI）

### 数据
- [x] template version / activation snapshot / stage transition / material verification / task history / probation history
- [x] Legacy mapping + DUAL_READ_COMPARE 对账命令
- [ ] 全量迁移演练（clean DB + upgrade from legacy snapshot，依赖 CI）

### 安全
- [x] tenant / scope / portal / high-sensitive / token / access audit / file security（代码层 + 单测）
- [ ] 真实渗透/HTTP 层测试（依赖 CI/测试环境）

### 技术
- [x] DB constraints / idempotency / transactions / outbox / retries / reconciliation / API version / migrations / rollback 命令
- [x] 迁移链 0001→0002→0003→0004（依赖 hr_structure 0001）
- [ ] PostgreSQL 目标库跑全迁移/锁/并发/Decimal/JSON/索引 EXPLAIN/rollback/restore（00 §26/§61）

### 前端
- [x] 管理端 + Portal 模板壳；状态组件按 00 §48
- [ ] 375/768/1280/1440 视觉回归 + accessibility + empty/error/blocked/partial（依赖 CI）

---

## 4. CI 恢复后必跑命令

```bash
# 1) 迁移与 system check
python manage.py check hr_onboarding
python manage.py makemigrations --check hr_onboarding
python manage.py migrate

# 2) 测试（S0-S11 全部契约）
python -m pytest hr_onboarding/tests/

# 3) 对账与切换演练
python manage.py hr05_reconcile_legacy --tenant 1
python manage.py hr05_switch_authority --tenant 1 --mode DUAL_READ_COMPARE --reason "演练" --report drill-001
python manage.py hr05_switch_authority --tenant 1 --mode LEGACY_ONBOARDING_ONLY --reason "回切演练"

# 4) 迁移回滚演练
python manage.py migrate hr_onboarding 0001   # 验证可回退（仅演练环境）
```

---

## 5. 已知环境阻塞（P0）

- 本机 shell 沙箱无后端：`git`/`python` 不可执行 → 无法真正 commit/Draft PR、跑 `django check`/`pytest`/`makemigrations`。
- `hr_time/models/__init__.py` 引用不存在的 `hr_time.models.policy`（总控台账冲突 #4）：会破坏全 Django 启动，属 HR11 窗口修复项；HR05 不越界修改。
- SQLite 单写者：真实并发（20 线程 Activate/工号）必须在 PostgreSQL CI 跑。

---

## 6. 结论（当前状态）

**S0-S11 代码与文档已全部落盘**，唯一未执行的是依赖 CI/目标库的机器验证与真实 E2E。
按 00 §158/05 §69 口径，当前不能输出 `HR05 READY FOR ACCEPTANCE`，阻断项为：
1. 本机 CI/shell 环境恢复后跑通 §4 全命令；
2. `hr_time` P0 import 修复（跨窗口依赖）；
3. HR04-S8 HANDOFF 真实交付后回填联调；
4. PostgreSQL 目标库验收。

满足后即可输出封板口令。
