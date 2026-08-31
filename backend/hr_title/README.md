# HR13 职称评审

> 设计事实源：`docs/13_HR13_职称评审_施工总册_终极版.md`

## 这个模块负责什么

HR13 是职称评审结果的业务 Authority，负责制度版本、申报批次、资格审查、代表性成果、专家/评委组织、评议表决、公示、复核以及正式职称历史。

## 不负责什么

- 不复制 HR03 人员主档、学历和任职事实。
- 不复制 HR09 教师资格/双师型事实。
- 不复制 HR10 培训/企业实践事实。
- 不把 HR12 考核结果直接当职称结果。
- 不替代 HR14 岗位聘任，也不直接修改 HR15 工资。

## 固定技术合同

- API：`/api/v1/hr/titles`
- Permission：`hr.title.*`
- Canonical events：`ProfessionalTitleResultEffective`、`ProfessionalTitleResultRevised`、`ProfessionalTitleResultRevoked`
- 数据库：MySQL-only
- Tenant/Scope/Permission：fail-closed
- FINAL/EFFECTIVE 结果只能更正、修订或撤销形成新事实，禁止原地覆盖。

## 小白看代码顺序

1. `models/`：职称制度、申报、评审、结果等事实结构。
2. `services/`：申报、审核、评议、公示、生效等写操作。
3. `selectors/`：列表、详情、历史、as-of 查询。
4. `api/`：统一 `/api/v1/hr/titles` 接口。
5. `templates/`：管理端页面。
6. `tests/`：权限、租户、状态机、并发、历史事实和 MySQL 验收。

当前分支只负责 HR13；跨模块写入必须通过对方 Authority Service / Provider / Event。
