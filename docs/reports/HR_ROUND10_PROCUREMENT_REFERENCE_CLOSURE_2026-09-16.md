# 高校人事系统 Round10：高校采购级验收参考补强与 HR18 接口同步收口报告

日期：2026-09-16  
唯一源码基线：`Yueke_University_HR_Round9_20260916.zip`  
外部参考：用户提供的 9 页《一站式非学历教育智慧前台建设项目采购清单》  
施工边界：仅云端沙箱源码副本；未连接 GitHub、生产服务器、生产数据库或真实学校接口。

## 1. 本轮对 PDF 的定位

这份 PDF **有较高参考价值，但不是 HR01～HR18 的业务蓝图，也不能逐条照抄成高校人事需求**。

它最有价值的是“采购人最终如何验系统”，尤其包括：

- 四级组织与数据权限；
- 教师本人工作台、分级管理与管理驾驶舱；
- 资质有效期、材料版本和历史依据；
- 积分/考核规则版本、过程可解释与历史快照；
- 数据中台/省级平台接口的字段映射、同步批次、异常、重试、幂等、人工补传；
- 操作日志、附件权限和敏感数据控制；
- 普通页面 3 秒、复杂统计 5 秒、至少 100 并发的验收指标；
- 数据、数据库结构、接口文档和规则配置可移交，避免供应商锁定。

Round10 因此不新建“非学历教育模块”，而是把这些条款转换成现有人事系统的**采购级验收合同**，优先补现有底座中真实可见的缺口。

## 2. 对照现有系统后的结论

### 2.1 已有能力，不重复造轮子

现有源码已经具备较深的相关底座：

- HR01 / HR17：本人工作台、统一待办/服务入口；
- 统一 RBAC、多租户、组织/数据范围与权限 fail-closed；
- HR09：教师资格/双师/证书有效期、到期风险、续证/撤销、历史 as-of 证据；
- HR12：考核规则、结果快照、确认、异议、更正、归档与多级 reviewer；
- HR18：字段映射版本、冻结数据集、异步交换 Job、租约、自动重试、幂等、回执、对账和 dead-letter；
- 全局：审计、附件权限、Excel、部署/备份/验收脚本。

因此 Round10 没有为了“看起来功能更多”再复制一套门户、资质或考核模块。

### 2.2 真实缺口

HR18 原来虽然已经有底层重试和 dead-letter，但管理侧还缺采购验收常见的两件事：

1. **同步运行状态可直接核查**：目标字段映射、最近状态、最近成功时间、待处理/成功/对账/失败数量需要在一个工作区内可见；
2. **最终失败可人工处置**：需要单条/批量人工重试，而且不能通过“把失败 Job 状态改回 QUEUED”来抹掉原始失败证据。

Round10 围绕这两个缺口施工。

## 3. HR18 同步健康工作台

`backend/hr_data/exchange_api.py` 的 exchange workbench 现在为每个目标映射输出：

- 当前 `mapping`；
- mapping `contentHash`；
- `pendingCount`；
- `transmittedCount`；
- `reconciledCount`；
- `failureCount`（历史最终失败总数）；
- `unresolvedFailureCount`（仍需人工处理）；
- `latestJobStatus` / `latestJobNo` / `latestErrorCode`；
- `lastSuccessAt`；
- `successSemantics`。

### 成功时间不再混淆

如果交换目标 `expectedReceipt=true`：

- 仅 `RECONCILED` 才作为端到端最近成功；
- 只把报文发出去但未完成回执/对账，不能显示成最终成功。

如果 `expectedReceipt=false`：

- `TRANSMITTED` 可作为最近成功。

这避免管理页面把“HTTP 已发出”冒充“对方系统已确认并对账成功”。

### 历史失败与当前待处理分离

原失败 Job 必须长期保留为 `DEAD_LETTER` 才有审计价值，因此“历史最终失败总数”不会随着人工重试消失。

Round10 新增 `unresolvedFailureCount`，只统计 dead-letter 仍未解决的失败。前端分别显示：

- `待人工处理`；
- `历史最终失败`。

这样既符合运维工作队列，又不牺牲历史证据。

## 4. 人工重试不是改状态，而是追加 successor

新增 `ExchangeJob` 来源字段：

- `retry_of_job`；
- `manual_retry_reason`；
- `manual_retry_by`。

迁移：`backend/hr_data/migrations/0019_exchange_manual_retry_provenance.py`

### 单条重试

API：

`POST /api/v1/hr/data/exchange/jobs/{job_id}/retry/`

只允许源 Job 已进入 `DEAD_LETTER`。

服务执行：

1. tenant-scoped `select_for_update()` 锁定原失败 Job；
2. 锁定对应 `ExchangeDeadLetter`；
3. 校验人工原因、幂等键、新 Job 编号、重试次数；
4. 创建新的 `QUEUED` successor Job；
5. successor 保存 `retry_of_job`、操作人和原因；
6. successor 成功创建后，才把 dead-letter 标记 `resolved_at`；
7. 原 Job 状态、原 attempts、原 dead-letter 原因/时间/快照不被覆盖。

整个操作位于一个数据库事务中。

### 精确幂等

同一 idempotency key 只有在以下内容仍与首次命令一致时才返回同一 successor：

- retry source；
- dataset version；
- target mapping version；
- snapshot hash；
- new job number；
- manual retry reason；
- max attempts。

同一幂等键换原因、换编号或换 retry 参数，直接 `EXCHANGE_IDEMPOTENCY_CONFLICT`，避免客户端错误重放被静默吞掉。

### 批量重试

API：

`POST /api/v1/hr/data/exchange/jobs/retry-batch/`

- 每批 1～100 条；
- 每条仍独立走 tenant + dead-letter + idempotency 校验；
- 返回每条成功/失败结果；
- `partial=true` 明确表示部分成功；
- 不会因为 99 条成功、1 条失败就伪装成“全部成功”。

## 5. 前端操作工作区

`frontend/static/hr/js/pages/hr18-actions.js` 已增加：

- 交换目标同步健康表；
- 字段映射数量；
- 最近状态和最近错误；
- 根据目标契约区分“最近传输成功”与“最近对账完成”；
- 待处理 / 已传输 / 已对账 / 待人工处理 / 历史最终失败；
- 单条“人工重试”；
- “批量重试失败任务”；
- 重试原因输入；
- 成功后明确提示“失败任务已保留，新任务进入队列”。

页面没有提供“删除失败记录”“把 DEAD_LETTER 改回 QUEUED”之类会破坏审计的捷径。

## 6. 从采购 PDF 固化的性能验收门

新增：`scripts/run_procurement_performance_probe.py`

默认验收参数直接采用本轮参考清单：

- 普通页面：`<= 3000 ms`；
- 复杂统计：`<= 5000 ms`；
- 并发：`100`；
- 默认每 URL 100 个请求。

为了避免误伤环境：

- **只发 GET**；
- 没有 `--allow-load` 明确确认时拒绝执行；
- 并发上限 200；
- 不自动跟随 302 登录重定向，防止未登录时把登录页误测成业务页；
- 输出证据中只保存 header 名称，不保存 Cookie / Authorization 值；
- URL query string 不写入证据，避免 token 泄漏。

示例（只能在已授权 QA/预发布环境运行）：

```bash
python scripts/run_procurement_performance_probe.py \
  --allow-load \
  --normal-url https://qa.example.edu/hr/ \
  --normal-url https://qa.example.edu/hr/staff/ \
  --analytics-url https://qa.example.edu/hr/data/ \
  --header "Cookie: <QA_SESSION_COOKIE>" \
  --concurrency 100 \
  --requests-per-url 100 \
  --output-json docs/reports/acceptance_evidence/procurement-performance.json
```

**本云端沙箱未执行真实负载。** 没有目标 QA 服务、真实 MySQL/Redis、脱敏数据和合法登录会话时，静态存在这个脚本不等于性能已通过。

## 7. 本轮发现并修正的实现级问题

在 Round10 自检中，第一次实现人工重试来源字段时，静态搜索虽然能找到字段名，但字段最初落到了另一个 `SubmissionDispatchJob` 类，而 `ExchangeJob` 的 `_IDENTITY_FIELDS` 已经引用它们。

如果不继续做 class-scoped 检查，Django 运行时创建 retry successor 会直接因未知字段失败。

本轮已在封包前修正：

- 三个字段只存在于 `ExchangeJob`；
- `SubmissionDispatchJob` 不含该字段；
- source `Meta.indexes` 与 0019 migration 的 `idx_hr18_exchange_retry_of` 一致；
- Round10 静态门改成按 class block 检查，防止今后“全文件字符串存在但放错模型”再次误绿。

## 8. 新增与修改的关键文件

新增：

- `backend/hr_data/migrations/0019_exchange_manual_retry_provenance.py`
- `scripts/check_hr18_procurement_sync_contract.py`
- `scripts/run_procurement_performance_probe.py`
- `tests/round10/test_procurement_sync_contract.py`
- `docs/reports/HR_ROUND10_PROCUREMENT_REFERENCE_CLOSURE_2026-09-16.md`
- `10_ROUND10_START_HERE.md`

修改：

- `backend/hr_data/models.py`
- `backend/hr_data/services/exchange_service.py`
- `backend/hr_data/exchange_api.py`
- `backend/hr_data/api_urls.py`
- `backend/hr_data/tests/test_exchange_service.py`
- `backend/hr_data/tests/test_exchange_api.py`
- `frontend/static/hr/js/pages/hr18-actions.js`
- `00_CHATGPT_START_HERE.md`

## 9. 已执行门禁

当前沙箱已真实执行：

- Round10 纯源码 unittest：10/10 PASS；
- Round10 HR18 procurement sync 静态门：24/24 PASS；
- Round2～Round10 纯源码回归（Round8 以独立静态门形式承接）：**169/169 PASS**；
- HR10 import 静态门：**20/20 PASS**；
- HR10 canonical staff identity 静态门：**53/53 PASS**；
- Round10 HR18 procurement sync 静态门：**24/24 PASS**；
- 全仓 Python AST：**3,148 文件，0 错误**；
- 全仓 JavaScript `node --check`：**253 文件，0 错误**；
- performance probe 缺少 `--allow-load` 时：真实返回拒绝执行，PASS。

## 10. 尚未宣称通过的动态项

当前执行器实际 `import django` 返回 `ModuleNotFoundError: No module named 'django'`。以下必须在有 Django + MySQL + Redis + QA 登录会话的环境执行后，才能放行：

1. `makemigrations --check --dry-run` 确认 source model 与 migration state 无 drift；
2. MySQL 执行 0019 升级与回滚/恢复演练；
3. `test_exchange_service` 新增人工重试 TransactionTestCase；
4. `test_exchange_api` 单条/批量人工重试接口测试；
5. 两个 worker/两管理员并发 retry 同一 dead-letter，只允许一个 successor；
6. 真实 provider 故障 → 自动重试 → dead-letter → 人工重试 → 成功 → 回执 → 对账；
7. 浏览器实际操作 HR18 工作区；
8. 脱敏真实数据下普通页面 3 秒、复杂统计 5 秒、100 并发；
9. 学校真实统一认证、数据中台、省级平台接口联调。

因此本轮封包状态仍应是：

**SOURCE_CODE_CANDIDATE / NOT_RELEASED**

## 11. 下一轮建议

继续沿 PDF 的“真实采购验收条款”补，而不是扩菜单：

1. 把学校级数据移交/可迁移能力做成可执行 export + restore + verify 门；
2. 将 HR09 资质、HR12 考核、HR18 同步的采购验收证据统一进入“学校验收证据包”；
3. 在 QA 环境跑 100 并发与 3s/5s 门禁；
4. 有真实接口规范后，再接统一认证、学校数据中台和省级平台，不用 mock 冒充已联通。
