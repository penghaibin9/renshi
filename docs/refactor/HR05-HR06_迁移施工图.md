# HR05-HR06 迁移施工图

> 施工线 C：`agent/refactor-c-hr05-hr06`
> 接管目标：`agent/renshi-takeover-cleanup-20260810`
> 权威文档：`05_HR05_入职管理_施工总册_终极版.md`、`06_HR06_人事异动_施工总册_终极版.md`

## 1. 目录归属

| 模块 | 新 Authority 目录 | 旧能力来源 | 裁决 |
|---|---|---|---|
| HR05 入职管理 | `hr_onboarding/` | `onboarding/`，以及 HR04 招聘转录用交接 | **REWRITE**：可安全复用 task/portal/workflow UI，正式 Activation/入职事实必须归 HR05 |
| HR06 人事异动 | `hr_changes/` | `employee` 当前任职快照、旧 save hook/signal 中的调动变更逻辑 | **REWRITE**：异动申请、审批、生效和历史事实独立建模，禁止只改 current snapshot |

## 2. 小白目录规则

HR05/HR06 的写业务统一进入各自 `services/`；读业务进入 `selectors/`；跨域只走 `providers/command/event`。旧 `onboarding/`、`employee/` 只做迁移来源/兼容投影，不再承载新正式规则。

## 3. 搬迁顺序

1. HR05 先盘点 onboarding task/stage/portal 与新入职案例、材料、核验、激活事实的对应关系。
2. 把 HR04→HR05 交接固定为显式命令/事件，杜绝直接复制 Candidate 后静默生成 Employee。
3. HR06 盘点调岗、转部门、任职变化、状态变化及 signal/save hook 副作用，逐项迁入 domain service + outbox。
4. 任何异动必须保留 effective date、前后事实、审批依据和审计；今天的变更不能改写历史。
5. 新旧双读对账通过后才冻结 legacy formal writes，最后再做旧页面/代码清理。

## 4. 当前已落地骨架

`hr_onboarding/` 与 `hr_changes/` 已有 README、`module_contract.py`、合同测试和模块入口说明，可以继续在既有目录中逐块搬运。

## 5. 下一块代码

优先施工 **HR05 legacy onboarding stage/task 只读 adapter + 映射测试**；随后施工 **HR06 current snapshot→effective-dated change fact 的第一条调岗链路**，但保留旧入口作为只读/兼容直到对账完成。
