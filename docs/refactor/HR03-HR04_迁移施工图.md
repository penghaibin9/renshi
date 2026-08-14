# HR03-HR04 迁移施工图

> 施工线 B：`agent/refactor-b-hr03-hr04`
> 接管目标：`agent/renshi-takeover-cleanup-20260810`
> 权威文档：`03_HR03_教职工主档_施工总册_终极版.md`、`04_HR04_招聘与人才引进_施工总册_终极版.md`

## 1. 目录归属

| 模块 | 新 Authority 目录 | 旧能力来源 | 裁决 |
|---|---|---|---|
| HR03 教职工主档 | `hr_staff/` | `employee.Employee` / `EmployeeWorkInformation` 及其当前快照 | **REWRITE + PROJECT**：新人员/任职事实为 Authority，旧 Employee 只做兼容投影 |
| HR04 招聘与人才引进 | `hr_recruitment/` | `recruitment/` | **REWRITE**：可安全复用 pipeline/UI/filter/portal 技术，但 Candidate/Stage 不能继续充当正式 Authority |

## 2. 小白目录规则

HR03、HR04 新业务只进入各自模块的 `models.py`、`services/`、`selectors/`、`providers/`、`api/`、`tests/`、`README.md`。旧 `employee/`、`recruitment/` 只能作为迁移来源/兼容层，不再新增正式规则。

## 3. 搬迁顺序

1. 盘点 Employee/WorkInformation 与 HR03 人员、任职、教育/履历字段映射，保留来源与 trust level。
2. HR03 建立新 Authority → legacy projection，禁止“写 HR03 失败就静默回写 Employee”。
3. HR04 先搬招聘流程编排技术，再逐步替换正式 Candidate/Offer/Hire 事实；流程 UI 可以复用，Authority 不复用。
4. 招聘转录用只能经 HR04→HR05 明确命令/事件交接，不能直接改 HR03 current snapshot。
5. 双读对账和越权/租户测试通过后再冻结旧写入口。

## 4. 当前已落地骨架

`hr_staff/` 与 `hr_recruitment/` 已有 README、`module_contract.py`、合同测试和 AppConfig 边界说明。本施工图作为后续搬代码的唯一目录导航。

## 5. 下一块代码

优先施工 **HR03 Employee/WorkInformation legacy read projection 与映射测试**；HR04 随后把一个招聘列表读取链路改为 `hr_recruitment` selector/provider，先不删除原 recruitment 页面。
