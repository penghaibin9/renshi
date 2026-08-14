# HR04 招聘管理

这是 HR04 的模块入口。HR04 负责招聘计划、职位、候选人、面试、录用和招聘过程事实；正式入职后由 HR05/HR03 接管人员事实。

## 小白先看这里

- `models/`：招聘计划、职位、候选人、面试、录用等模型。
- `services/`：招聘流程写操作。
- `selectors/`：招聘列表和统计查询。
- `api/`：正式 API。
- `jobs/`：异步任务。
- `integrations/`：跨模块/外部系统适配。
- `policies/` / `permissions.py`：业务规则和权限。
- `projections/`：可重建投影。
- `tests/`：招聘流程、越权和租户测试。

## 重构硬规则

1. 招聘完成不能直接篡改 HR03 主档，必须通过正式服务/事件交接。
2. RETURN 与 REJECT 必须区分。
3. 导入导出必须异步化或可审计，Excel 有错误行反馈。
4. 所有学校数据 tenant fail-closed。
5. 正式 API 统一 `/api/v1/hr/...`。
