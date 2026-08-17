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
