# HR18 人事数据中心

> 设计事实源：`docs/18_HR18_人事数据中心_施工总册_终极版.md`

## 这个模块负责什么

HR18 是人事数据与报送治理 Authority：指标定义与口径版本、历史 as-of、标准/自助报表、数据质量、数据集/交换、正式上报快照、审批、回执、更正和档案。

## 接管策略

现有 Horilla `report/` 不直接删除。动态筛选、Pivot、Saved ReportTemplate 等可作为交互技术底座；正式 Metric Registry、数据质量、交换、报送 Authority 新建在 `hr_data`。业务事实错误必须回源 HR02–HR17 修复。

## 固定技术合同

- API：`/api/v1/hr/data`
- Permission：`hr.data.*`
- HR18 是正式 `MetricDefinition / Population / Dimension / as-of` Authority。
- 数据库：MySQL-only
- Tenant/Scope/Permission：fail-closed
- Provider UNAVAILABLE 不能当 0；PARTIAL 不能当 COMPLETE。
- 正式导出/交换/报送必须真实异步并保存快照、版本、回执和更正链。

## 小白看代码顺序

1. `models/`：指标、报表、质量规则、数据集、交换和报送定义/快照。
2. `providers/`：只读消费 HR02–HR17 正式事实。
3. `services/`：指标计算、质量检查、交换、报送审批/提交/更正。
4. `selectors/`：总览、专题、历史 as-of 和下钻查询。
5. `api/`：统一 `/api/v1/hr/data`。
6. `tests/`：口径版本、历史、租户、数据质量、异步、回执和 MySQL 验收。

## 异步数据交换运行合同

交换链固定为：冻结数据集版本 → 冻结目标映射 → 创建持久任务 → worker
租约传输 → 外部回执 → 自动对账。每一步都按 tenant 查询，任务命令使用唯一
`idempotencyKey`，传输尝试使用稳定的“任务 key + 尝试序号”。

- 数据集 API：`POST /api/v1/hr/data/exchange/datasets/`
- 目标映射 API：`POST /api/v1/hr/data/exchange/targets/`
- 排队 API：`POST /api/v1/hr/data/exchange/jobs/`
- 回执 API：`POST /api/v1/hr/data/exchange/jobs/{jobId}/receipt/`
- 对账 API：`POST /api/v1/hr/data/exchange/jobs/{jobId}/reconcile/`
- 失败队列：`GET /api/v1/hr/data/exchange/dead-letters/`
- worker：`python manage.py run_hr18_exchange_worker --limit 50`

这些接口统一要求 `hr.data.exchange`。数据集只保存安全存储的 `payloadRef`、
SHA-256、记录数和来源证据，不在目标映射或日志里保存 endpoint、token、password
等凭据。Provider 路径由部署方放在 `HR18_EXCHANGE_PROVIDERS` 映射中；未配置时
任务保持 QUEUED 并明确返回 `EXCHANGE_PROVIDER_UNAVAILABLE`，不会伪造成功。

Provider 是 callable，接收 `tenant_id`、`job`、`dataset`、`target_mapping`、
`idempotency_key`、`actor_user_id`，成功必须返回：

```python
{"transmitted": True, "dispatchRef": "durable-remote-id", "providerVersion": "v1"}
```

外部调用发生在数据库事务外。worker 只凭当前 lease token 回写；旧 worker 即使
晚返回，也不能覆盖新 lease。达到最大重试次数或回执对账不一致会进入不可篡改的
dead-letter 证据队列。
