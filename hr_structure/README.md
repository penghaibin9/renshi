# HR02 组织岗位

这是 HR02 的模块入口。HR02 是组织、部门、岗位、编制及有效期历史的权威来源，是 HR03 人员主档和后续业务的基础。

## 小白先看这里

- `models/`：组织、岗位等正式事实模型。
- `services/`：新增、调整、停用等写操作。
- `selectors/`：组织树、岗位、历史查询。
- `api/`：正式 API。
- `imports/`：Excel 导入、校验、错误行处理。
- `projections/`：可重建的查询投影。
- `scope.py` / `permissions.py`：学校与数据范围权限。
- `tests/`：业务和越权测试。

## 重构硬规则

1. 组织/岗位历史使用 `[effective_from, effective_to)`，不能覆盖过去事实。
2. tenant 缺失时查询必须 fail-closed。
3. Excel 必须有模板、校验、错误行和审计。
4. 不允许其他模块直接修改 HR02 权威表。
5. 正式 API 统一 `/api/v1/hr/...`。
