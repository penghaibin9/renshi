# HR01-HR02 迁移施工图

> 施工线 A：`agent/refactor-a-hr01-hr02`
> 接管目标：`agent/renshi-takeover-cleanup-20260810`
> 权威文档：`01_HR01_人事工作台_施工总册_终极版.md`、`02_HR02_组织机构与编制岗位_施工总册_终极版.md`

## 1. 目录归属

| 模块 | 新 Authority 目录 | 旧能力来源 | 裁决 |
|---|---|---|---|
| HR01 人事工作台 | `hr_control_center/` | 旧 dashboard / employee / report 中的管理聚合能力只作为数据来源候选 | **REWRITE 聚合层**：HR01 不接管教职工、组织等业务事实，只通过 provider/selectors 聚合 |
| HR02 组织机构与编制岗位 | `hr_structure/` | `base.Company` / `Department` / `JobPosition` | **REWRITE + ADAPT**：Tenant/Organization/Position 成为新 Authority，旧对象逐步只读 |

## 2. 小白目录规则

每个模块只认：`models.py`（事实）→ `services/`（写业务）→ `selectors/`（读业务）→ `providers/`（跨域输出）→ `api/`（接口）→ `tests/`（验收）→ `README.md`（入口说明）。模板/静态资源后续只放模块自身目录，禁止再把 HR01/HR02 新逻辑散回 `employee/`、`base/`、`report/`。

## 3. 搬迁顺序

1. 先保留所有旧目录，不删除；锁定旧模型和写入口。
2. HR02 先完成 Company→Tenant、Department→HrOrganization、JobPosition→HrPosition 的读对账与历史/有效期规则。
3. HR01 只消费 HR02/HR03 等 provider，禁止直接跨域改表。
4. API 统一收口到 `/api/v1/hr/...`，旧 deep link 只做兼容 redirect/adapter。
5. 新旧双读对账通过后再冻结 legacy formal writes；最后才允许清理旧代码。

## 4. 当前已落地骨架

`hr_control_center/` 与 `hr_structure/` 已有 README、`module_contract.py` 和合同测试。本施工图之后的代码提交必须在合同边界内推进，不再新造平行目录。

## 5. 下一块代码

优先施工 **HR02 legacy projection/read adapter + 对账测试**，然后让 HR01 的组织维度筛选只通过 HR02 provider 获取；不得为了赶进度直接读取 `base.Department` 作为长期 Authority。
