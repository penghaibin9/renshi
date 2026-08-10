# HR12 考核与绩效

> HR12 负责“按冻结政策和证据完成考核，并形成不可随意改写的结果事实”。它消费 HR03/HR09/HR10/HR11 的受控事实，但不反向篡改这些源数据。

## 权威职责

- 政策、周期、周期快照和考核对象快照；
- 目标、证据、自评、评议、多主体评价、校准；
- 最终结果、通知、确认、异议、修订和归档。

## 目录怎么找

- `models/`：按 policy / cycle / goal / evidence / case / result 分文件，属于当前推荐结构；
- `services/` / `domain/`：流程、计算、冻结和跨域规则；
- `api/`：接口；
- `templates/`：页面；
- `tests/`：业务、约束、权限、迁移和跨域回归；
- `module_contract.py`：模块边界及必须稳定的数据库约束名。

## 数据库红线

`uniq_cycle_tenant_no_type`、`uniq_goal_tenant_code`、`uniq_reviewer_case_role` 已属于既有数据库合同。重构或自动迁移不得把它们无故删除并退化为匿名 `unique_together`。

`AppConfig.ready()` 只保留 signal 启动挂钩，URL 必须由中央路由显式注册。

新接口统一 `/api/v1/hr`。
