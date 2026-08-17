# HR14 岗位聘任

> 设计事实源：`docs/14_HR14_岗位聘任_施工总册_终极版.md`

## 这个模块负责什么

HR14 是岗位聘任 Authority，负责聘任制度、岗位额度快照、聘任批次、申报竞聘、资格审查、评议排序、拟聘公示、正式聘任、聘期变更与历史档案。

## 不负责什么

- HR02 才是组织、岗位、编制/职数和空岗事实源。
- HR03 才是人员主档和 Assignment 历史事实源。
- HR13 职称取得不等于 HR14 已聘任。
- HR14 正式聘任只触发 HR15 薪酬复核，不直接计算或修改工资。

## 固定技术合同

- API：`/api/v1/hr/appointments`
- Permission：`hr.appointment.*`
- Canonical event：`PositionAppointmentEffective`
- 数据库：MySQL-only
- Tenant/Scope/Permission：fail-closed
- 正式聘任结果不可静默覆盖，岗位占用/并发竞聘必须有事务与锁验证。

## 小白看代码顺序

1. `models/`：规则、批次、申请、评议、聘任和历史。
2. `services/`：资格、评议、公示、生效和变更写操作。
3. `selectors/`：岗位供给、候选人、结果、历史查询。
4. `api/`：统一 `/api/v1/hr/appointments`。
5. `templates/`：管理端竞聘/评审工作区。
6. `tests/`：租户、权限、并发、额度、历史事实和 MySQL 验收。
