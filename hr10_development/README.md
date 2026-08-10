# HR10 教师发展

这是 HR10 的模块入口。HR10 负责培训、学习经历、发展项目、能力成长和相关证明材料；正式人员身份仍由 HR03 权威维护。

## 小白先看这里

- `models/`：发展项目、学习记录、认证/证明和暂存数据。
- `services/`：正式写操作和数据升级。
- `selectors/`：学习记录、项目、统计和历史查询。
- `api/`：正式 API。
- `imports/` / staging 模型：旧数据导入、人工核验、错误处理。
- `policies/` / `permissions.py`：规则和权限。
- `tests/`：迁移、导入、越权、租户和历史测试。

## 重构硬规则

1. staging 数据不能未经核验直接升级为正式事实。
2. 已确认的学习/发展事实保留来源、时间和审计。
3. tenant / permission fail-closed。
4. migration state 必须与模型一致，禁止靠跳过 gate 假绿。
5. 正式 API 统一 `/api/v1/hr/...`。
