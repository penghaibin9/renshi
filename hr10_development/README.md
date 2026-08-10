# HR10 教师发展与培训进修

> HR10 管教师“如何发展”：培训、进修、企业实践、完成情况和发展成果。资质认定归 HR09，绩效考核归 HR12。

## 权威职责

- 教师发展计划、需求、预算；
- 培训项目、班次、报名、参与、完成；
- 进修与企业实践全过程；
- 发展成果、指标台账、风险；
- 旧 Horilla 数据先进入 `legacy/staging.py`，人工核验后才能升级为正式事实。

## 目录怎么找

- `models/`：正式教师发展事实；
- `legacy/`：旧数据导入与 staging，**不能当垃圾目录删除**；
- `services/` / `domain/`：业务规则和跨域命令；
- `api/`：接口；
- `templates/`：页面；
- `tests/`：流程、迁移、权限、跨域测试；
- `module_contract.py`：模块边界。

## 迁移红线

`HrDevelopmentStagingRow` 与 `HrDevelopmentImportJob` 属于历史接管合同。它们必须从 `models/__init__.py` 显式注册；`makemigrations` 若提议删除 staging/import 表，应视为阻断性错误，而不是自动接受。

新接口统一 `/api/v1/hr`。
