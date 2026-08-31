# HR12 考核管理

这是 HR12 的模块入口。HR12 负责考核政策、周期、目标、指标、评审流程、证据和结果事实。

## 小白先看这里

- `models/`：政策、周期、目标、Case、证据、评审和结果模型。
- `services/`：建周期、发起、评审、归档等写操作。
- `selectors/`：考核对象、进度、结果和历史查询。
- `api/`：正式 API。
- `policies/` / `permissions.py`：规则、角色和数据范围。
- `signals.py`：仅保留必要事件绑定，禁止隐藏业务写入。
- `tests/`：模型合同、migration、权限、租户、状态机和结果测试。

## 重构硬规则

1. Policy / Cycle / Case / Result 分层，避免一个表承担所有事实。
2. FINAL/CLOSED 后不可静默修改。
3. 模型状态必须与 migration 历史一致；命名约束不降级为匿名约束。
4. tenant / permission / audit fail-closed。
5. 正式 API 统一 `/api/v1/hr/...`。
