# HR05 入职管理

这是 HR05 的模块入口。HR05 负责录用后的入职办理、材料、任务、审批和正式入职交接；人员主档最终由 HR03 权威维护。

## 小白先看这里

- `models/`：入职单、任务、材料、审批等模型。
- `services/`：入职流程写操作和状态转换。
- `selectors/`：待办、进度、人员入职查询。
- `api/`：正式 API。
- `jobs/`：异步任务。
- `integrations/`：HR04/HR03 等跨模块交接。
- `policies/` / `permissions.py`：规则、角色和数据范围。
- `tests/`：状态机、越权、租户和交接测试。

## 重构硬规则

1. 招聘录用事实来自 HR04；正式人员事实交给 HR03。
2. 入职流程必须可追溯，不允许半成功无审计。
3. tenant / permission / audit fail-closed。
4. 批量材料和 Excel 操作必须可校验、可回滚、可审计。
5. 正式 API 统一 `/api/v1/hr/...`。
