# HR06 人事异动

这是 HR06 的模块入口。HR06 负责人事异动申请、审批、执行和历史留痕，例如调岗、调部门、任职变化等。

## 小白先看这里

- `models/`：异动 Case、动作、历史和审计模型。
- `services/`：状态机、审批、执行写操作。
- `selectors/`：异动列表、历史和待办查询。
- `api/`：正式 API。
- `jobs/`：异步任务。
- `integrations/`：与 HR02/HR03 等模块的正式交接。
- `policies/` / `permissions.py`：业务规则和权限。
- `projections/`：查询投影。
- `tests/`：并发、幂等、权限、租户和历史事实测试。

## 重构硬规则

1. FINAL/EFFECTIVE 后不可静默修改。
2. 异动执行必须通过权威模块服务更新 HR02/HR03，不直接跨表写。
3. Person Transition Lock、幂等和事务必须覆盖关键执行链。
4. RETURN 与 REJECT 区分。
5. 正式 API 统一 `/api/v1/hr/...`。
