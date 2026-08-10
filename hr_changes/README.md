# HR06 人事异动

> HR06 处理“这个人的人事状态发生了什么变化、何时生效、如何回放”。这是高并发和跨域风险最高的核心模块之一。

## 权威职责

- 调动、转岗、离岗等异动案例；
- 审批、退回、驳回、生效和关闭；
- 以命令 + 可靠事件通知 HR02/HR03/HR07 等域完成各自事实变更。

## 必须保留的生产机制

- Person Transition Lock；
- 幂等键；
- Outbox/Inbox；
- tenant fail-closed；
- FINAL/EFFECTIVE/CLOSED 不可变；
- `[effective_from, effective_to)` 历史语义。

## 目录怎么找

`models/` 事实，`services/`/`domain/` 规则与命令，`api/` 接口，`templates/` 页面，`tests/` 并发/幂等/跨域回归，`module_contract.py` 边界。

## 重构红线

重构只能让入口更清晰，不能把锁、幂等、Outbox、审计或状态机删掉换“简单代码”。新 API 统一 `/api/v1/hr`。
